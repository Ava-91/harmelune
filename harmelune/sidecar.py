"""Restricted JSONL bridge for the desktop UI.

Only explicitly enumerated scan, review, dry-run, and gated Safe/Reconcile/Mirror
execution commands are exposed. Both execution paths require an exact preview
token and typed confirmation, validate backup locations against both libraries,
and use the existing verified-backup transaction engine. Reconcile applies only
explicit decisions and never deletes files. Standard output is reserved for one
JSON object per line; diagnostics go to standard error. The desktop frontend
cannot execute shell commands or arbitrary Python code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import sys
import threading
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .direction import select_master
from .freshness import StalePlanError
from .dry_run import DryRunResult
from .models import SyncMode
from .reconcile import ReconcileDecision
from .services import ScanBundle, execute_workflow, preview_workflow, scan_libraries
from .path_safety import validate_backup_root
from .backup import MANIFEST_NAME, BackupVerificationError, restore_verified_backup, verify_backup_contents
from .health import build_health_report
from .settings import default_config_dir

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 1_048_576
PAGE_SIZE = 100
MAX_PAGE_SIZE = 200
_PLANS: dict[str, tuple[ScanBundle, list[dict[str, object]]]] = {}
MAX_HISTORY_ITEMS = 1000
_ACTIVE_SCAN_EVENT: threading.Event | None = None
_SCAN_LOCK = threading.Lock()
_OUTPUT_LOCK = threading.Lock()


def _history_path() -> Path:
    return default_config_dir() / "operation-history.sqlite3"


def _record_history(mode: str, report: dict[str, object]) -> bool:
    """Persist an operation without hiding its result if history storage fails."""
    try:
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=3) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, mode TEXT NOT NULL, report_json TEXT NOT NULL)")
            connection.execute("INSERT INTO operations (id, timestamp, mode, report_json) VALUES (?, ?, ?, ?)",
                (uuid4().hex, datetime.now(timezone.utc).isoformat(), mode,
                 json.dumps(report, ensure_ascii=False, separators=(",", ":"))))
            connection.execute("DELETE FROM operations WHERE id NOT IN (SELECT id FROM operations ORDER BY timestamp DESC, rowid DESC LIMIT ?)", (MAX_HISTORY_ITEMS,))
        return True
    except (OSError, sqlite3.Error, TypeError, ValueError):
        traceback.print_exc(file=sys.stderr)
        return False


def _load_history() -> tuple[list[dict[str, object]], str | None]:
    path = _history_path()
    if not path.exists():
        return [], None
    try:
        with sqlite3.connect(path, timeout=3) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT id, timestamp, mode, report_json FROM operations ORDER BY timestamp DESC, rowid DESC LIMIT ?", (MAX_HISTORY_ITEMS,)).fetchall()
        items = []
        for row in rows:
            try:
                report = json.loads(row["report_json"])
            except json.JSONDecodeError:
                report = {"history_error": "Stored report could not be decoded."}
            items.append({"id": row["id"], "timestamp": row["timestamp"], "mode": row["mode"], "report": report})
        return items, None
    except (OSError, sqlite3.Error) as exc:
        return [], str(exc)


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _write(payload: dict[str, object]) -> None:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _OUTPUT_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


def _error(request_id: object, code: str, message: str) -> None:
    _write({
        "version": PROTOCOL_VERSION,
        "id": request_id if isinstance(request_id, str) else None,
        "type": "error",
        "ok": False,
        "error": {"code": code, "message": message},
    })


def _track(track) -> dict[str, object]:
    return {
        "path": str(track.path),
        "name": track.path.name,
        "title": track.display_title,
        "artist": track.display_artist,
        "album": track.display_album,
        "duration": track.duration,
        "size": track.size,
        "side": track.side,
        "sha256": track.file_hash,
        "artwork_count": track.artwork_count,
    }


def _rows(bundle: ScanBundle) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match in bundle.plan.matches:
        if not match.confirmed:
            category, label = "fuzzy", "Uncertain match"
        elif match.metadata_conflict or match.artwork_conflict:
            category, label = "conflicts", "Conflict"
        else:
            category, label = "exact", "Confirmed match"
        rows.append({
            "category": category,
            "label": label,
            "a": _track(match.library_a),
            "b": _track(match.library_b),
            "confidence": match.confidence,
            "confirmed": match.confirmed,
            "metadata_conflict": match.metadata_conflict,
            "artwork_conflict": match.artwork_conflict,
            "reasons": list(match.reasons),
        })
    for track in bundle.plan.library_a_only:
        rows.append({"category": "a_only", "label": "Only in Library A", "a": _track(track), "b": None})
    for track in bundle.plan.library_b_only:
        rows.append({"category": "b_only", "label": "Only in Library B", "a": None, "b": _track(track)})
    return rows


def _summary(bundle: ScanBundle, rows: list[dict[str, object]]) -> dict[str, object]:
    counts = {key: 0 for key in ("exact", "fuzzy", "conflicts", "a_only", "b_only")}
    for row in rows:
        category = row.get("category")
        if category in counts:
            counts[str(category)] += 1
    return {
        "counts": counts,
        "library_a": str(bundle.library_a),
        "library_b": str(bundle.library_b),
        "tracks_a": len(bundle.scan_a.tracks),
        "tracks_b": len(bundle.scan_b.tracks),
        "errors_a": list(bundle.scan_a.errors),
        "errors_b": list(bundle.scan_b.errors),
        "enumeration_complete_a": bundle.scan_a.enumeration_complete,
        "enumeration_complete_b": bundle.scan_b.enumeration_complete,
        "unsupported_audio_a": bundle.scan_a.unsupported_audio_files,
        "unsupported_audio_b": bundle.scan_b.unsupported_audio_files,
        "safe_to_preview": (
            not bundle.scan_a.errors and not bundle.scan_b.errors
            and bundle.scan_a.enumeration_complete and bundle.scan_b.enumeration_complete
        ),
    }



def _safe_preview_token(plan_id: str, master_library: str, preview: DryRunResult) -> str:
    """Bind an execution approval to the exact read-only preview shown to the user."""
    payload = {
        "plan_id": plan_id,
        "master_library": master_library,
        "operations": [
            {"kind": operation.kind.value, "source": str(operation.source) if operation.source is not None else None,
             "destination": str(operation.destination)}
            for operation in preview.operations
        ],
        "skipped": preview.skipped,
        "blocked": preview.blocked,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()



def _reconcile_preview_token(plan_id: str, decisions: dict[str, ReconcileDecision], backup_root: Path, preview: DryRunResult) -> str:
    payload = {
        "plan_id": plan_id,
        "decisions": {key: value.value for key, value in sorted(decisions.items())},
        "backup_root": str(backup_root.resolve(strict=False)),
        "operations": [{"kind": op.kind.value, "source": str(op.source) if op.source is not None else None, "destination": str(op.destination)} for op in preview.operations],
        "skipped": preview.skipped,
        "blocked": preview.blocked,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mirror_preview_token(plan_id: str, master_library: str, backup_root: Path, preview: DryRunResult) -> str:
    """Bind Mirror approval to direction, backup root, and every planned mutation."""
    payload = {
        "plan_id": plan_id,
        "master_library": master_library,
        "backup_root": str(backup_root.resolve(strict=False)),
        "operations": [
            {"kind": op.kind.value, "source": str(op.source) if op.source is not None else None,
             "destination": str(op.destination)}
            for op in preview.operations
        ],
        "skipped": preview.skipped,
        "blocked": preview.blocked,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()



def _restore_preview_token(backup: Path, target: Path, safety_root: Path, backup_id: str) -> str:
    payload = {
        "backup": str(backup.resolve()),
        "target": str(target.resolve()),
        "safety_root": str(safety_root.resolve(strict=False)),
        "backup_id": backup_id,
        "manifest_sha256": hashlib.sha256((backup / MANIFEST_NAME).read_bytes()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _require_string(params: dict[str, object], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("INVALID_ARGUMENT", f"{name} must be a non-empty string.")
    if len(value) > 32768:
        raise ProtocolError("INVALID_ARGUMENT", f"{name} is too long.")
    return value.strip()


def _page(rows: list[dict[str, object]], params: dict[str, object]) -> dict[str, object]:
    offset = params.get("offset", 0)
    limit = params.get("limit", PAGE_SIZE)
    query = params.get("query", "")
    category = params.get("category", "all")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ProtocolError("INVALID_ARGUMENT", "offset must be a non-negative integer.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        raise ProtocolError("INVALID_ARGUMENT", f"limit must be between 1 and {MAX_PAGE_SIZE}.")
    if not isinstance(query, str):
        raise ProtocolError("INVALID_ARGUMENT", "query must be a string.")
    if not isinstance(category, str) or category not in {"all", "exact", "fuzzy", "conflicts", "a_only", "b_only"}:
        raise ProtocolError("INVALID_ARGUMENT", "category is not supported.")
    needle = query.casefold().strip()
    filtered = []
    for row in rows:
        if category != "all" and row.get("category") != category:
            continue
        if needle and needle not in json.dumps(row, ensure_ascii=False).casefold():
            continue
        filtered.append(row)
    return {
        "rows": filtered[offset:offset + limit],
        "offset": offset,
        "limit": limit,
        "total": len(filtered),
        "has_more": offset + limit < len(filtered),
    }


def _handle(request: object, emit_progress, cancel_event: threading.Event | None = None) -> tuple[dict[str, object], bool]:
    if not isinstance(request, dict):
        raise ProtocolError("INVALID_REQUEST", "Each JSONL request must be an object.")
    request_id = request.get("id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise ProtocolError("INVALID_REQUEST", "id must be a non-empty string of at most 128 characters.")
    version = request.get("version")
    if version != PROTOCOL_VERSION or isinstance(version, bool):
        raise ProtocolError("UNSUPPORTED_VERSION", f"Supported protocol version is {PROTOCOL_VERSION}.")
    command = request.get("command")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError("INVALID_ARGUMENT", "params must be an object.")

    if command in {"hello", "ping"}:
        result: dict[str, object] = {
            "engine": "harmelune-python",
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": ["scan", "cancel_scan", "list_tracks", "health", "history", "preview_safe", "preview_reconcile", "execute_safe", "execute_reconcile", "preview_mirror", "execute_mirror", "preview_restore", "execute_restore", "shutdown"],
            "read_only": False,
        }
        return ({"version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True, "result": result}, False)

    if command == "scan":
        library_a = _require_string(params, "library_a")
        library_b = _require_string(params, "library_b")
        threshold = params.get("fuzzy_threshold", 0.88)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ProtocolError("INVALID_ARGUMENT", "fuzzy_threshold must be a number from 0 to 1.")
        def progress(side: str, visited: int) -> None:
            emit_progress({
                "version": PROTOCOL_VERSION, "id": request_id, "type": "progress",
                "event": "scan_progress", "side": side, "visited": visited,
            })
        bundle = scan_libraries(library_a, library_b, fuzzy_threshold=float(threshold), progress=progress, cancel=cancel_event.is_set if cancel_event is not None else None)
        if bundle is None:
            raise ProtocolError("SCAN_CANCELLED", "Scan was cancelled before comparison completed.")
        plan_id = uuid4().hex
        rows = _rows(bundle)
        _PLANS[plan_id] = (bundle, rows)
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {
                "plan_id": plan_id,
                "summary": _summary(bundle, rows),
                "page": _page(rows, {"offset": 0, "limit": PAGE_SIZE}),
            },
        }, False)

    if command == "cancel_scan":
        with _SCAN_LOCK:
            active = _ACTIVE_SCAN_EVENT
            if active is not None:
                active.set()
        return ({"version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
                 "result": {"accepted": active is not None, "message": "Scan cancellation requested." if active else "No scan is running."}}, False)

    if command == "history":
        items, history_error = _load_history()
        return ({"version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
                 "result": {"items": items, "scope": "persistent_local_history", "retention_limit": MAX_HISTORY_ITEMS, "storage_error": history_error}}, False)

    if command == "health":
        plan_id = _require_string(params, "plan_id")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, _rows_for_plan = stored
        return ({"version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
                 "result": asdict(build_health_report(bundle.scan_a, bundle.scan_b, bundle.plan))}, False)

    if command == "list_tracks":
        plan_id = _require_string(params, "plan_id")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": _page(stored[1], params),
        }, False)

    if command == "preview_safe":
        plan_id = _require_string(params, "plan_id")
        master_library = _require_string(params, "master_library")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, rows = stored
        summary = _summary(bundle, rows)
        if not summary["safe_to_preview"]:
            raise ProtocolError("SCAN_INCOMPLETE", "A dry-run preview is blocked because one or both library scans are incomplete or have errors.")
        try:
            direction = select_master(bundle.library_a, bundle.library_b, master_library)
            preview: DryRunResult = preview_workflow(bundle.plan, SyncMode.SAFE, direction)
        except StalePlanError as exc:
            raise ProtocolError("STALE_PLAN", f"{exc} Rescan both libraries before previewing again.") from exc
        except (OSError, ValueError) as exc:
            raise ProtocolError("PREVIEW_BLOCKED", str(exc)) from exc
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {
                "mode": "safe",
                "status": preview.status,
                "preview_token": _safe_preview_token(plan_id, master_library, preview),
                "operations": [
                    {
                        "kind": operation.kind.value,
                        "source": str(operation.source) if operation.source is not None else None,
                        "destination": str(operation.destination),
                    }
                    for operation in preview.operations
                ],
                "skipped": preview.skipped,
                "blocked": preview.blocked,
                "operation_count": len(preview.operations),
                "mutations_enabled": False,
            },
        }, False)


    if command == "execute_safe":
        plan_id = _require_string(params, "plan_id")
        master_library = _require_string(params, "master_library")
        backup_root = _require_string(params, "backup_root")
        confirmation = params.get("confirmation")
        supplied_token = _require_string(params, "preview_token")
        if confirmation != "APPLY SAFE":
            raise ProtocolError("CONFIRMATION_REQUIRED", 'Safe execution requires exact confirmation text: APPLY SAFE.')
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, rows = stored
        summary = _summary(bundle, rows)
        if not summary["safe_to_preview"]:
            raise ProtocolError("SCAN_INCOMPLETE", "Safe execution is blocked because one or both scans are incomplete or have errors.")
        try:
            direction = select_master(bundle.library_a, bundle.library_b, master_library)
            validate_backup_root(backup_root, (bundle.library_a, bundle.library_b))
            preview = preview_workflow(bundle.plan, SyncMode.SAFE, direction)
            expected_token = _safe_preview_token(plan_id, master_library, preview)
            if not hmac.compare_digest(supplied_token, expected_token):
                raise ProtocolError("PREVIEW_MISMATCH", "The approved preview no longer matches. Build a fresh preview and confirm it again.")
            if preview.status != "SUCCESS" or preview.blocked:
                raise ProtocolError("PREVIEW_BLOCKED", "Safe execution is blocked because the preview contains blocked operations.")
            if any(operation.kind.value != "copy" for operation in preview.operations):
                raise ProtocolError("UNSAFE_OPERATION", "Safe execution permits copy-only operations.")
            report = execute_workflow(bundle.plan, SyncMode.SAFE, direction, backup_root)
        except StalePlanError as exc:
            raise ProtocolError("STALE_PLAN", f"{exc} Rescan both libraries before executing.") from exc
        except ProtocolError:
            raise
        except (OSError, ValueError) as exc:
            raise ProtocolError("EXECUTION_BLOCKED", str(exc)) from exc
        report_data = report.to_dict()
        history_persisted = _record_history("safe", report_data)
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {"execution": report_data, "mutations_enabled": True, "history_persisted": history_persisted},
        }, False)

    if command == "preview_reconcile":
        plan_id = _require_string(params, "plan_id")
        backup_root = _require_string(params, "backup_root")
        raw_decisions = params.get("decisions")
        if not isinstance(raw_decisions, dict):
            raise ProtocolError("INVALID_ARGUMENT", "decisions must be an object mapping review item keys to explicit decisions.")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, rows = stored
        summary = _summary(bundle, rows)
        if not summary["safe_to_preview"]:
            raise ProtocolError("SCAN_INCOMPLETE", "Reconcile preview is blocked because one or both library scans are incomplete or have errors.")
        allowed = {decision.value: decision for decision in ReconcileDecision}
        decisions: dict[str, ReconcileDecision] = {}
        for key, value in raw_decisions.items():
            if not isinstance(key, str) or not key or len(key) > 32768:
                raise ProtocolError("INVALID_ARGUMENT", "Each decision key must be a non-empty string.")
            if not isinstance(value, str) or value not in allowed:
                raise ProtocolError("INVALID_ARGUMENT", f"Unsupported Reconcile decision for {key!r}.")
            decisions[key] = allowed[value]
        try:
            normalized_backup_root = validate_backup_root(backup_root, (bundle.library_a, bundle.library_b))
            preview = preview_workflow(bundle.plan, SyncMode.RECONCILE, select_master(bundle.library_a, bundle.library_b, "library_a"), decisions=decisions, backup_root=normalized_backup_root)
        except StalePlanError as exc:
            raise ProtocolError("STALE_PLAN", f"{exc} Rescan both libraries before previewing again.") from exc
        except (OSError, ValueError) as exc:
            message = str(exc)
            code = "DECISIONS_REQUIRED" if "explicit decision" in message.casefold() else "PREVIEW_BLOCKED"
            raise ProtocolError(code, message) from exc
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {
                "mode": "reconcile", "status": preview.status, "preview_token": _reconcile_preview_token(plan_id, decisions, normalized_backup_root, preview),
                "operations": [{"kind": op.kind.value, "source": str(op.source) if op.source is not None else None, "destination": str(op.destination)} for op in preview.operations],
                "skipped": preview.skipped, "blocked": preview.blocked,
                "operation_count": len(preview.operations), "mutations_enabled": False,
            },
        }, False)
    if command == "execute_reconcile":
        plan_id = _require_string(params, "plan_id")
        backup_root_raw = _require_string(params, "backup_root")
        supplied_token = _require_string(params, "preview_token")
        if params.get("confirmation") != "APPLY RECONCILE":
            raise ProtocolError("CONFIRMATION_REQUIRED", 'Reconcile execution requires exact confirmation text: APPLY RECONCILE.')
        raw_decisions = params.get("decisions")
        if not isinstance(raw_decisions, dict):
            raise ProtocolError("INVALID_ARGUMENT", "decisions must be an object mapping review item keys to explicit decisions.")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, rows = stored
        if not _summary(bundle, rows)["safe_to_preview"]:
            raise ProtocolError("SCAN_INCOMPLETE", "Reconcile execution is blocked because one or both scans are incomplete or have errors.")
        allowed = {decision.value: decision for decision in ReconcileDecision}
        decisions: dict[str, ReconcileDecision] = {}
        for key, value in raw_decisions.items():
            if not isinstance(key, str) or not key or len(key) > 32768:
                raise ProtocolError("INVALID_ARGUMENT", "Each decision key must be a non-empty string.")
            if not isinstance(value, str) or value not in allowed:
                raise ProtocolError("INVALID_ARGUMENT", f"Unsupported Reconcile decision for {key!r}.")
            decisions[key] = allowed[value]
        try:
            normalized_backup_root = validate_backup_root(backup_root_raw, (bundle.library_a, bundle.library_b))
            preview = preview_workflow(bundle.plan, SyncMode.RECONCILE, select_master(bundle.library_a, bundle.library_b, "library_a"), decisions=decisions, backup_root=normalized_backup_root)
            expected_token = _reconcile_preview_token(plan_id, decisions, normalized_backup_root, preview)
            if not hmac.compare_digest(supplied_token, expected_token):
                raise ProtocolError("PREVIEW_MISMATCH", "The reviewed Reconcile plan, decisions, or backup location changed. Build a fresh preview and confirm it again.")
            if preview.status != "SUCCESS" or preview.blocked:
                raise ProtocolError("PREVIEW_BLOCKED", "Reconcile execution is blocked until every required item has an explicit valid decision and the preview has no blockers.")
            if any(operation.kind.value not in {"copy", "replace"} for operation in preview.operations):
                raise ProtocolError("UNSAFE_OPERATION", "Reconcile permits only explicit copy or replace operations; delete is never allowed.")
            report = execute_workflow(bundle.plan, SyncMode.RECONCILE, select_master(bundle.library_a, bundle.library_b, "library_a"), normalized_backup_root, decisions=decisions)
        except StalePlanError as exc:
            raise ProtocolError("STALE_PLAN", f"{exc} Rescan both libraries before executing.") from exc
        except ProtocolError:
            raise
        except (OSError, ValueError) as exc:
            raise ProtocolError("EXECUTION_BLOCKED", str(exc)) from exc
        report_data = report.to_dict()
        history_persisted = _record_history("reconcile", report_data)
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {"execution": report_data, "mutations_enabled": True, "history_persisted": history_persisted},
        }, False)

    if command == "preview_mirror":
        plan_id = _require_string(params, "plan_id")
        master_library = _require_string(params, "master_library")
        backup_root_raw = _require_string(params, "backup_root")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, rows = stored
        if not _summary(bundle, rows)["safe_to_preview"]:
            raise ProtocolError("SCAN_INCOMPLETE", "Mirror preview is blocked because one or both scans are incomplete or have errors.")
        try:
            direction = select_master(bundle.library_a, bundle.library_b, master_library)
            backup_root = validate_backup_root(backup_root_raw, (bundle.library_a, bundle.library_b))
            preview = preview_workflow(bundle.plan, SyncMode.MIRROR, direction)
        except StalePlanError as exc:
            raise ProtocolError("STALE_PLAN", f"{exc} Rescan both libraries before previewing again.") from exc
        except (OSError, ValueError) as exc:
            raise ProtocolError("PREVIEW_BLOCKED", str(exc)) from exc
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {
                "mode": "mirror", "status": preview.status,
                "preview_token": _mirror_preview_token(plan_id, master_library, backup_root, preview),
                "operations": [
                    {"kind": op.kind.value, "source": str(op.source) if op.source is not None else None,
                     "destination": str(op.destination)}
                    for op in preview.operations
                ],
                "skipped": preview.skipped, "blocked": preview.blocked,
                "operation_count": len(preview.operations),
                "deletion_count": sum(op.kind.value == "delete" for op in preview.operations),
                "replacement_count": sum(op.kind.value == "replace" for op in preview.operations),
                "mutations_enabled": False,
            },
        }, False)

    if command == "execute_mirror":
        plan_id = _require_string(params, "plan_id")
        master_library = _require_string(params, "master_library")
        backup_root_raw = _require_string(params, "backup_root")
        supplied_token = _require_string(params, "preview_token")
        if params.get("confirmation") != "MIRROR":
            raise ProtocolError("CONFIRMATION_REQUIRED", 'Mirror execution requires exact confirmation text: MIRROR.')
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "This scan is no longer available. Scan both libraries again.")
        bundle, rows = stored
        if not _summary(bundle, rows)["safe_to_preview"]:
            raise ProtocolError("SCAN_INCOMPLETE", "Mirror execution is blocked because one or both scans are incomplete or have errors.")
        try:
            direction = select_master(bundle.library_a, bundle.library_b, master_library)
            backup_root = validate_backup_root(backup_root_raw, (bundle.library_a, bundle.library_b))
            preview = preview_workflow(bundle.plan, SyncMode.MIRROR, direction)
            expected_token = _mirror_preview_token(plan_id, master_library, backup_root, preview)
            if not hmac.compare_digest(supplied_token, expected_token):
                raise ProtocolError("PREVIEW_MISMATCH", "The reviewed Mirror operations, direction, or backup location changed. Build a fresh preview and confirm again.")
            if preview.status != "SUCCESS" or preview.blocked:
                raise ProtocolError("PREVIEW_BLOCKED", "Mirror execution is blocked until all unresolved matches are reviewed and the preview has no blockers.")
            if any(operation.kind.value not in {"copy", "replace", "delete"} for operation in preview.operations):
                raise ProtocolError("UNSAFE_OPERATION", "Mirror contains an unsupported operation.")
            report = execute_workflow(bundle.plan, SyncMode.MIRROR, direction, backup_root, confirmation="MIRROR")
        except StalePlanError as exc:
            raise ProtocolError("STALE_PLAN", f"{exc} Rescan both libraries before executing.") from exc
        except ProtocolError:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise ProtocolError("EXECUTION_BLOCKED", str(exc)) from exc
        report_data = report.to_dict()
        history_persisted = _record_history("mirror", report_data)
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {"execution": report_data, "mutations_enabled": True, "history_persisted": history_persisted},
        }, False)

    if command == "preview_restore":
        plan_id = _require_string(params, "plan_id")
        backup_raw = _require_string(params, "backup_path")
        target_key = _require_string(params, "target_library")
        safety_root_raw = _require_string(params, "safety_backup_root")
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "Scan the intended libraries first so the restore target can be verified.")
        bundle, _rows_for_plan = stored
        libraries = (bundle.library_a, bundle.library_b)
        if target_key == "library_a":
            target = bundle.library_a
        elif target_key == "library_b":
            target = bundle.library_b
        else:
            raise ProtocolError("INVALID_ARGUMENT", "target_library must be library_a or library_b.")
        try:
            backup = Path(backup_raw).expanduser().resolve(strict=True)
            if not backup.is_dir():
                raise ValueError("Backup path must point to a backup directory.")
            validate_backup_root(backup, libraries)
            safety_root = validate_backup_root(safety_root_raw, libraries)
            if backup == safety_root or backup.is_relative_to(safety_root) or safety_root.is_relative_to(backup):
                raise ValueError("Safety backup location must be separate from the selected restore backup.")
            info = verify_backup_contents(backup)
            manifest = json.loads((backup / MANIFEST_NAME).read_text(encoding="utf-8"))
            source_path = manifest.get("source_path")
            if not isinstance(source_path, str) or Path(source_path).resolve(strict=False) != target.resolve():
                raise ValueError("Backup source identity does not match the selected library. Choose a backup made from this exact library path.")
            token = _restore_preview_token(backup, target, safety_root, info.backup_id)
        except (OSError, ValueError, BackupVerificationError) as exc:
            raise ProtocolError("RESTORE_PREVIEW_BLOCKED", str(exc)) from exc
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {
                "mode": "restore", "status": "READY", "backup_path": str(backup),
                "backup_id": info.backup_id, "file_count": info.file_count, "size_bytes": info.size_bytes,
                "target_library": target_key, "target_path": str(target),
                "safety_backup_root": str(safety_root), "preview_token": token,
                "mutations_enabled": False,
                "warning": "Restore replaces the target library contents with this backup. A verified safety backup is created first.",
            },
        }, False)

    if command == "execute_restore":
        plan_id = _require_string(params, "plan_id")
        backup_raw = _require_string(params, "backup_path")
        target_key = _require_string(params, "target_library")
        safety_root_raw = _require_string(params, "safety_backup_root")
        supplied_token = _require_string(params, "preview_token")
        if params.get("confirmation") != "RESTORE":
            raise ProtocolError("CONFIRMATION_REQUIRED", 'Restore requires exact confirmation text: RESTORE.')
        stored = _PLANS.get(plan_id)
        if stored is None:
            raise ProtocolError("PLAN_NOT_FOUND", "Scan the intended libraries first so the restore target can be verified.")
        bundle, _rows_for_plan = stored
        libraries = (bundle.library_a, bundle.library_b)
        if target_key == "library_a":
            target = bundle.library_a
        elif target_key == "library_b":
            target = bundle.library_b
        else:
            raise ProtocolError("INVALID_ARGUMENT", "target_library must be library_a or library_b.")
        try:
            backup = Path(backup_raw).expanduser().resolve(strict=True)
            validate_backup_root(backup, libraries)
            safety_root = validate_backup_root(safety_root_raw, libraries)
            if backup == safety_root or backup.is_relative_to(safety_root) or safety_root.is_relative_to(backup):
                raise ValueError("Safety backup location must be separate from the selected restore backup.")
            info = verify_backup_contents(backup)
            manifest = json.loads((backup / MANIFEST_NAME).read_text(encoding="utf-8"))
            source_path = manifest.get("source_path")
            if not isinstance(source_path, str) or Path(source_path).resolve(strict=False) != target.resolve():
                raise ValueError("Backup source identity does not match the selected library path.")
            expected_token = _restore_preview_token(backup, target, safety_root, info.backup_id)
            if not hmac.compare_digest(supplied_token, expected_token):
                raise ProtocolError("PREVIEW_MISMATCH", "Restore preview changed. Verify the backup and build a fresh preview.")
            result = restore_verified_backup(backup, target, safety_root, confirmation="RESTORE")
        except ProtocolError:
            raise
        except (OSError, ValueError, RuntimeError, BackupVerificationError) as exc:
            raise ProtocolError("RESTORE_FAILED", str(exc)) from exc
        restore_report = {"mode": "restore", "restored": result.restored, "recovered": result.recovered,
                          "safety_backup": str(result.safety_backup) if result.safety_backup else None,
                          "error": result.error, "mutations_enabled": True}
        history_persisted = _record_history("restore", restore_report)
        restore_report["history_persisted"] = history_persisted
        return ({"version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
                 "result": restore_report}, False)

    if command == "shutdown":
        return ({
            "version": PROTOCOL_VERSION, "id": request_id, "type": "result", "ok": True,
            "result": {"stopped": True},
        }, True)

    raise ProtocolError("UNKNOWN_COMMAND", "Supported commands are hello, ping, scan, list_tracks, preview_safe, preview_reconcile, execute_safe, execute_reconcile, preview_mirror, execute_mirror, preview_restore, execute_restore, and shutdown.")


def main() -> int:
    global _ACTIVE_SCAN_EVENT
    scan_thread: threading.Thread | None = None

    def finish_scan(request: object, event: threading.Event) -> None:
        global _ACTIVE_SCAN_EVENT
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            response, _ = _handle(request, _write, event)
            _write(response)
        except ProtocolError as exc:
            _error(request_id, exc.code, str(exc))
        except Exception:
            traceback.print_exc(file=sys.stderr)
            _error(request_id, "INTERNAL_ERROR", "The Python engine failed while processing the scan.")
        finally:
            with _SCAN_LOCK:
                if _ACTIVE_SCAN_EVENT is event:
                    _ACTIVE_SCAN_EVENT = None

    while True:
        raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not raw:
            with _SCAN_LOCK:
                active = _ACTIVE_SCAN_EVENT
                if active is not None:
                    active.set()
            if scan_thread is not None:
                scan_thread.join(timeout=10)
            return 0
        if len(raw) > MAX_REQUEST_BYTES:
            while raw and not raw.endswith(b"\n"):
                raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            _error(None, "REQUEST_TOO_LARGE", "JSONL request exceeded the 1 MiB limit.")
            continue
        request: object = None
        try:
            request = json.loads(raw.decode("utf-8"))
            request_id = request.get("id") if isinstance(request, dict) else None
            command = request.get("command") if isinstance(request, dict) else None
            if command == "scan":
                with _SCAN_LOCK:
                    if _ACTIVE_SCAN_EVENT is not None:
                        _error(request_id, "SCAN_ALREADY_RUNNING", "A library scan is already running.")
                        continue
                    event = threading.Event()
                    _ACTIVE_SCAN_EVENT = event
                scan_thread = threading.Thread(target=finish_scan, args=(request, event), name="harmelune-sidecar-scan", daemon=True)
                scan_thread.start()
                continue
            if command == "shutdown":
                with _SCAN_LOCK:
                    active = _ACTIVE_SCAN_EVENT
                    if active is not None:
                        active.set()
                if scan_thread is not None and scan_thread.is_alive():
                    scan_thread.join(timeout=10)
                    if scan_thread.is_alive():
                        _error(request_id, "SCAN_SHUTDOWN_TIMEOUT", "The scan did not stop within the shutdown deadline.")
                        continue
            response, should_stop = _handle(request, lambda event: _write(event))
            _write(response)
            if should_stop:
                return 0
        except UnicodeDecodeError:
            _error(None, "INVALID_ENCODING", "Requests must be UTF-8.")
        except json.JSONDecodeError:
            _error(None, "INVALID_JSON", "Request line is not valid JSON.")
        except ProtocolError as exc:
            request_id = request.get("id") if isinstance(request, dict) else None
            _error(request_id, exc.code, str(exc))
        except (OSError, ValueError) as exc:
            request_id = request.get("id") if isinstance(request, dict) else None
            _error(request_id, "REQUEST_FAILED", str(exc))
        except Exception:
            request_id = request.get("id") if isinstance(request, dict) else None
            traceback.print_exc(file=sys.stderr)
            _error(request_id, "INTERNAL_ERROR", "The Python engine failed while processing the request.")


if __name__ == "__main__":
    raise SystemExit(main())
