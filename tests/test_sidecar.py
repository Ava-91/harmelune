from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

from harmelune.sidecar import PROTOCOL_VERSION


def write_wav(path: Path, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes((b"\x01\x00" if frames % 2 else b"\x00\x00") * frames)


def request(request_id: str, command: str, params: dict | None = None, version: int = PROTOCOL_VERSION) -> str:
    return json.dumps({"version": version, "id": request_id, "command": command, "params": params or {}})


def run_sidecar(input_lines: list[str], config_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(config_dir)
    return subprocess.run(
        [sys.executable, "-m", "harmelune.sidecar"],
        input="\n".join(input_lines) + "\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def parse_output(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_protocol_hello_and_shutdown_are_clean(tmp_path: Path):
    completed = run_sidecar([
        request("hello-1", "hello"),
        request("stop-1", "shutdown"),
    ], tmp_path / "config")

    assert completed.returncode == 0
    messages = parse_output(completed.stdout)
    assert [message["type"] for message in messages] == ["result", "result"]
    assert messages[0]["result"]["protocol_version"] == PROTOCOL_VERSION
    assert messages[1]["result"]["stopped"] is True
    assert completed.stderr == ""


def test_protocol_rejects_bad_json_versions_and_unknown_commands(tmp_path: Path):
    completed = run_sidecar([
        "{not-json",
        request("old-version", "hello", version=999),
        request("unknown", "run_shell", {"command": "anything"}),
        request("stop", "shutdown"),
    ], tmp_path / "config")

    messages = parse_output(completed.stdout)
    assert completed.returncode == 0
    assert [message["error"]["code"] for message in messages[:3]] == [
        "INVALID_JSON", "UNSUPPORTED_VERSION", "UNKNOWN_COMMAND"
    ]
    assert all(message["ok"] is False for message in messages[:3])


def test_scan_progress_and_paged_rows_use_only_temp_synthetic_audio(tmp_path: Path):
    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    completed = run_sidecar([
        request("scan-1", "scan", {"library_a": str(a), "library_b": str(b)}),
        request("stop-1", "shutdown"),
    ], tmp_path / "config")

    assert completed.returncode == 0
    messages = parse_output(completed.stdout)
    progress = [message for message in messages if message["type"] == "progress"]
    scan = next(message for message in messages if message.get("id") == "scan-1" and message["type"] == "result")
    assert progress
    assert {message["side"] for message in progress} == {"a", "b"}
    assert scan["result"]["summary"]["tracks_a"] == 1
    assert scan["result"]["summary"]["tracks_b"] == 1
    assert scan["result"]["page"]["total"] == 2
    assert not scan["result"]["summary"]["errors_a"]
    assert not scan["result"]["summary"]["errors_b"]


def test_list_tracks_rejects_unknown_scan_id(tmp_path: Path):
    completed = run_sidecar([
        request("page-1", "list_tracks", {"plan_id": "not-a-real-plan"}),
        request("stop-1", "shutdown"),
    ], tmp_path / "config")
    messages = parse_output(completed.stdout)
    assert messages[0]["type"] == "error"
    assert messages[0]["error"]["code"] == "PLAN_NOT_FOUND"

def test_page_filters_categories_and_paginates_without_losing_totals():
    from harmelune.sidecar import _page

    rows = [
        {"category": "a_only", "label": "Only in Library A", "a": {"title": "First song"}},
        {"category": "b_only", "label": "Only in Library B", "b": {"title": "Second song"}},
        {"category": "a_only", "label": "Only in Library A", "a": {"title": "Third song"}},
    ]

    first = _page(rows, {"offset": 0, "limit": 2})
    second = _page(rows, {"offset": 2, "limit": 2})
    filtered = _page(rows, {"offset": 0, "limit": 10, "category": "a_only", "query": "song"})

    assert first["total"] == 3
    assert len(first["rows"]) == 2
    assert first["has_more"] is True
    assert len(second["rows"]) == 1
    assert second["has_more"] is False
    assert filtered["total"] == 2
    assert all(row["category"] == "a_only" for row in filtered["rows"])


def test_page_rejects_invalid_pagination_and_filter_values():
    from harmelune.sidecar import ProtocolError, _page

    invalid_params = (
        {"offset": -1},
        {"offset": True},
        {"limit": 0},
        {"limit": 201},
        {"limit": False},
        {"query": 3},
        {"category": "delete"},
    )
    for params in invalid_params:
        try:
            _page([], params)
        except ProtocolError as exc:
            assert exc.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError(f"Expected invalid arguments to be rejected: {params!r}")


def test_safe_preview_returns_operations_without_changing_synthetic_libraries(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    before_a = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()}
    before_b = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    preview, _ = sidecar._handle(
        json.loads(request("preview", "preview_safe", {"plan_id": plan_id, "master_library": "library_a"})),
        lambda _event: None,
    )

    assert preview["ok"] is True
    assert preview["result"]["mode"] == "safe"
    assert preview["result"]["mutations_enabled"] is False
    assert preview["result"]["operation_count"] >= 1
    assert all(op["kind"] == "copy" for op in preview["result"]["operations"])
    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()} == before_a
    assert {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()} == before_b


def test_safe_preview_requires_valid_plan_and_explicit_master(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]

    for params, expected in [
        ({"plan_id": "missing", "master_library": "library_a"}, "PLAN_NOT_FOUND"),
        ({"plan_id": plan_id, "master_library": "unknown"}, "PREVIEW_BLOCKED"),
    ]:
        try:
            sidecar._handle(json.loads(request("preview", "preview_safe", params)), lambda _event: None)
        except sidecar.ProtocolError as exc:
            assert exc.code == expected
        else:
            raise AssertionError(f"Expected {expected} for {params!r}")


def test_reconcile_preview_requires_explicit_decisions_and_separate_backup_root(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    backup_root = str(tmp_path / "separate-backups")

    blocked, _ = sidecar._handle(
        json.loads(request("missing-decisions", "preview_reconcile", {
            "plan_id": plan_id, "backup_root": backup_root, "decisions": {},
        })),
        lambda _event: None,
    )
    assert blocked["ok"] is True
    assert blocked["result"]["status"] == "BLOCKED"
    assert blocked["result"]["mutations_enabled"] is False
    assert blocked["result"]["blocked"]

    decisions = {
        f"a-only:{a / 'Only A.wav'}": "copy_a_to_b",
        f"b-only:{b / 'Only B.wav'}": "copy_b_to_a",
    }
    preview, _ = sidecar._handle(
        json.loads(request("complete-decisions", "preview_reconcile", {
            "plan_id": plan_id, "backup_root": backup_root, "decisions": decisions,
        })),
        lambda _event: None,
    )
    assert preview["ok"] is True
    assert preview["result"]["status"] == "SUCCESS"
    assert preview["result"]["operation_count"] == 2
    assert all(operation["kind"] == "copy" for operation in preview["result"]["operations"])
    assert not (tmp_path / "separate-backups").exists()
    assert (a / "Only A.wav").exists() and (b / "Only B.wav").exists()


def test_preview_reports_stale_plan_after_library_changes(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    write_wav(a / "added-after-scan.wav", 85)

    try:
        sidecar._handle(
            json.loads(request("stale", "preview_safe", {"plan_id": plan_id, "master_library": "library_a"})),
            lambda _event: None,
        )
    except sidecar.ProtocolError as exc:
        assert exc.code == "STALE_PLAN"
        assert "Scan both libraries again" in str(exc)
    else:
        raise AssertionError("A stale plan must not produce a preview.")



def test_mirror_preview_lists_deletions_and_execution_requires_exact_token_confirmation(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Keep from A.wav", 80)
    write_wav(b / "Delete from B.wav", 83)
    backup_root = tmp_path / "mirror-backups"
    before_a = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()}
    before_b = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    preview, _ = sidecar._handle(
        json.loads(request("preview-mirror", "preview_mirror", {
            "plan_id": plan_id, "master_library": "library_a", "backup_root": str(backup_root),
        })),
        lambda _event: None,
    )

    assert preview["ok"] is True
    assert preview["result"]["mode"] == "mirror"
    assert preview["result"]["mutations_enabled"] is False
    operations = preview["result"]["operations"]
    assert {operation["kind"] for operation in operations} == {"copy", "delete"}
    assert any(operation["kind"] == "delete" and operation["destination"] == str(b / "Delete from B.wav") for operation in operations)
    token = preview["result"]["preview_token"]

    for confirmation, supplied_token, expected_code in [
        ("mirror", token, "CONFIRMATION_REQUIRED"),
        ("MIRROR", "tampered-preview-token", "PREVIEW_MISMATCH"),
    ]:
        try:
            sidecar._handle(json.loads(request("blocked-mirror", "execute_mirror", {
                "plan_id": plan_id, "master_library": "library_a", "backup_root": str(backup_root),
                "preview_token": supplied_token, "confirmation": confirmation,
            })), lambda _event: None)
        except sidecar.ProtocolError as exc:
            assert exc.code == expected_code
        else:
            raise AssertionError(f"Mirror must reject invalid approval: {expected_code}")
    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()} == before_a
    assert {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()} == before_b
    assert not backup_root.exists()

    result, _ = sidecar._handle(
        json.loads(request("apply-mirror", "execute_mirror", {
            "plan_id": plan_id, "master_library": "library_a", "backup_root": str(backup_root),
            "preview_token": token, "confirmation": "MIRROR",
        })),
        lambda _event: None,
    )
    assert result["ok"] is True
    report = result["result"]["execution"]
    assert report["mode"] == "mirror"
    assert report["final_status"] == "SUCCESS"
    assert (b / "Keep from A.wav").read_bytes() == (a / "Keep from A.wav").read_bytes()
    assert not (b / "Delete from B.wav").exists()
    backup_dirs = list(backup_root.iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "Delete from B.wav").read_bytes() == before_b["Delete from B.wav"]
    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()} == before_a


def test_mirror_preview_rejects_backup_root_inside_either_library(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    for unsafe_root in (a / "backup", b / "backup"):
        try:
            sidecar._handle(json.loads(request("unsafe-mirror", "preview_mirror", {
                "plan_id": plan_id, "master_library": "library_a", "backup_root": str(unsafe_root),
            })), lambda _event: None)
        except sidecar.ProtocolError as exc:
            assert exc.code == "PREVIEW_BLOCKED"
        else:
            raise AssertionError("Mirror must reject backup roots inside either library.")



def test_safe_execution_requires_exact_confirmation_and_verified_preview(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    backup_root = tmp_path / "backups"
    before_a = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()}
    before_b = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    preview, _ = sidecar._handle(
        json.loads(request("preview", "preview_safe", {"plan_id": plan_id, "master_library": "library_a"})),
        lambda _event: None,
    )
    token = preview["result"]["preview_token"]

    try:
        sidecar._handle(json.loads(request("no-confirm", "execute_safe", {
            "plan_id": plan_id, "master_library": "library_a", "backup_root": str(backup_root),
            "preview_token": token, "confirmation": "yes",
        })), lambda _event: None)
    except sidecar.ProtocolError as exc:
        assert exc.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("Execution must reject a non-exact confirmation.")

    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()} == before_a
    assert {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()} == before_b
    assert not backup_root.exists()

    result, _ = sidecar._handle(
        json.loads(request("apply-safe", "execute_safe", {
            "plan_id": plan_id, "master_library": "library_a", "backup_root": str(backup_root),
            "preview_token": token, "confirmation": "APPLY SAFE",
        })),
        lambda _event: None,
    )
    assert result["ok"] is True
    report = result["result"]["execution"]
    assert report["mode"] == "safe"
    assert report["final_status"] == "SUCCESS"
    assert report["succeeded"] == 1
    assert len(report["backups"]) == 1
    assert (b / "Only A.wav").read_bytes() == (a / "Only A.wav").read_bytes()
    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()} == before_a
    backup_dirs = list(backup_root.iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "Only B.wav").read_bytes() == before_b["Only B.wav"]


def test_safe_execution_rejects_backup_inside_either_library_and_tampered_preview(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    preview, _ = sidecar._handle(
        json.loads(request("preview", "preview_safe", {"plan_id": plan_id, "master_library": "library_a"})),
        lambda _event: None,
    )
    token = preview["result"]["preview_token"]

    for backup_root, supplied_token, expected_code in [
        (str(a / "backups"), token, "EXECUTION_BLOCKED"),
        (str(b / "backups"), token, "EXECUTION_BLOCKED"),
        (str(tmp_path / "backups"), "not-the-preview-token", "PREVIEW_MISMATCH"),
    ]:
        try:
            sidecar._handle(json.loads(request("execute", "execute_safe", {
                "plan_id": plan_id, "master_library": "library_a", "backup_root": backup_root,
                "preview_token": supplied_token, "confirmation": "APPLY SAFE",
            })), lambda _event: None)
        except sidecar.ProtocolError as exc:
            assert exc.code == expected_code
        else:
            raise AssertionError(f"Expected {expected_code} for backup root {backup_root!r}")
    assert not (a / "backups").exists()
    assert not (b / "backups").exists()
    assert not (b / "Only A.wav").exists()


def test_safe_execution_rejects_stale_plan_without_creating_backup(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    backup_root = tmp_path / "backups"
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(
        json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})),
        lambda _event: None,
    )
    plan_id = scan["result"]["plan_id"]
    preview, _ = sidecar._handle(
        json.loads(request("preview", "preview_safe", {"plan_id": plan_id, "master_library": "library_a"})),
        lambda _event: None,
    )
    write_wav(a / "added-after-preview.wav", 91)

    try:
        sidecar._handle(json.loads(request("execute", "execute_safe", {
            "plan_id": plan_id, "master_library": "library_a", "backup_root": str(backup_root),
            "preview_token": preview["result"]["preview_token"], "confirmation": "APPLY SAFE",
        })), lambda _event: None)
    except sidecar.ProtocolError as exc:
        assert exc.code == "STALE_PLAN"
    else:
        raise AssertionError("Execution must reject a plan after either library changes.")
    assert not backup_root.exists()
    assert not (b / "Only A.wav").exists()


def test_reconcile_execution_requires_confirmation_and_applies_only_reviewed_decisions(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir(); b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    backup_root = tmp_path / "verified-backups"
    before_a = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()}
    before_b = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})), lambda _event: None)
    plan_id = scan["result"]["plan_id"]
    decisions = {f"a-only:{a / 'Only A.wav'}": "copy_a_to_b", f"b-only:{b / 'Only B.wav'}": "copy_b_to_a"}
    preview, _ = sidecar._handle(json.loads(request("preview", "preview_reconcile", {"plan_id": plan_id, "backup_root": str(backup_root), "decisions": decisions})), lambda _event: None)
    assert preview["ok"] is True and preview["result"]["status"] == "SUCCESS"
    assert preview["result"]["operation_count"] == 2
    assert preview["result"]["mutations_enabled"] is False
    token = preview["result"]["preview_token"]

    try:
        sidecar._handle(json.loads(request("no-confirm", "execute_reconcile", {"plan_id": plan_id, "backup_root": str(backup_root), "decisions": decisions, "preview_token": token, "confirmation": "yes"})), lambda _event: None)
    except sidecar.ProtocolError as exc:
        assert exc.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("Reconcile must require exact typed confirmation.")
    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()} == before_a
    assert {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()} == before_b
    assert not backup_root.exists()

    result, _ = sidecar._handle(json.loads(request("apply", "execute_reconcile", {"plan_id": plan_id, "backup_root": str(backup_root), "decisions": decisions, "preview_token": token, "confirmation": "APPLY RECONCILE"})), lambda _event: None)
    assert result["ok"] is True
    report = result["result"]["execution"]
    assert report["mode"] == "reconcile" and report["final_status"] == "SUCCESS"
    assert report["succeeded"] == 2 and report["failed"] == 0
    assert len(report["backups"]) == 2
    assert (b / "Only A.wav").read_bytes() == before_a["Only A.wav"]
    assert (a / "Only B.wav").read_bytes() == before_b["Only B.wav"]
    assert {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file() and p.name != ".music-sync-backup.json"} == {**before_a, "Only B.wav": before_b["Only B.wav"]}


def test_reconcile_execution_rejects_changed_decisions_backup_path_and_stale_plan(tmp_path: Path, monkeypatch):
    from harmelune import sidecar

    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir(); b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    backup_root = tmp_path / "verified-backups"
    monkeypatch.setattr(sidecar, "_PLANS", {})
    scan, _ = sidecar._handle(json.loads(request("scan", "scan", {"library_a": str(a), "library_b": str(b)})), lambda _event: None)
    plan_id = scan["result"]["plan_id"]
    decisions = {f"a-only:{a / 'Only A.wav'}": "copy_a_to_b", f"b-only:{b / 'Only B.wav'}": "skip"}
    preview, _ = sidecar._handle(json.loads(request("preview", "preview_reconcile", {"plan_id": plan_id, "backup_root": str(backup_root), "decisions": decisions})), lambda _event: None)
    token = preview["result"]["preview_token"]
    attempts = [
        (decisions | {f"b-only:{b / 'Only B.wav'}": "copy_b_to_a"}, str(backup_root), token, "PREVIEW_MISMATCH"),
        (decisions, str(a / "inside-backup"), token, "EXECUTION_BLOCKED"),
    ]
    for altered, backup, supplied_token, expected in attempts:
        try:
            sidecar._handle(json.loads(request("blocked", "execute_reconcile", {"plan_id": plan_id, "backup_root": backup, "decisions": altered, "preview_token": supplied_token, "confirmation": "APPLY RECONCILE"})), lambda _event: None)
        except sidecar.ProtocolError as exc:
            assert exc.code == expected
        else:
            raise AssertionError(f"Expected {expected} for altered decisions/backup root")
    assert not (b / "Only A.wav").exists()
    assert not (a / "inside-backup").exists()

    write_wav(a / "added-after-preview.wav", 91)
    try:
        sidecar._handle(json.loads(request("stale", "execute_reconcile", {"plan_id": plan_id, "backup_root": str(backup_root), "decisions": decisions, "preview_token": token, "confirmation": "APPLY RECONCILE"})), lambda _event: None)
    except sidecar.ProtocolError as exc:
        assert exc.code == "STALE_PLAN"
    else:
        raise AssertionError("Stale Reconcile plans must not execute.")
    assert not backup_root.exists()
    assert not (b / "Only A.wav").exists()