from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


JOURNAL_FORMAT = 1
TERMINAL_STATES = frozenset({"completed", "rolled_back", "partial", "abandoned"})


class JournalCorruptError(RuntimeError):
    """Raised when a journal exists but cannot be safely interpreted."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    created_at: str
    updated_at: str
    mode: str
    status: str = "in_progress"
    backup_paths: list[str] = field(default_factory=list)
    affected_paths: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    error: str | None = None
    recovery_note: str | None = None


class OperationJournal:
    """Durable local record of file operations; it never resumes work automatically.

    Keep this store in Harmelune's configuration directory, not inside either
    music library. Journal data contains paths and operation metadata, never audio.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read(self) -> list[OperationRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != JOURNAL_FORMAT:
                raise ValueError("unsupported journal format")
            rows = payload.get("operations")
            if not isinstance(rows, list):
                raise ValueError("operations must be a list")
            records = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("operation record must be an object")
                record = OperationRecord(**row)
                if not record.operation_id or not record.mode or not record.created_at:
                    raise ValueError("operation identity is incomplete")
                if record.status not in {"in_progress", *TERMINAL_STATES}:
                    raise ValueError("unknown operation status")
                if not all(isinstance(x, str) for x in record.backup_paths + record.affected_paths + record.completed_steps):
                    raise ValueError("journal path/step values must be strings")
                records.append(record)
            return records
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise JournalCorruptError(
                f"Operation journal cannot be read safely: {self.path}. "
                "Preserve this file for inspection; do not resume an operation automatically."
            ) from exc

    def _write(self, records: list[OperationRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": JOURNAL_FORMAT, "operations": [asdict(row) for row in records]}
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def begin(
        self,
        mode: str,
        *,
        backup_paths: list[str | Path] | None = None,
        affected_paths: list[str | Path] | None = None,
    ) -> OperationRecord:
        if not mode.strip():
            raise ValueError("mode must not be empty")
        with self._lock:
            rows = self._read()
            now = _now()
            record = OperationRecord(
                operation_id=uuid4().hex,
                created_at=now,
                updated_at=now,
                mode=mode,
                backup_paths=[str(Path(p)) for p in (backup_paths or [])],
                affected_paths=[str(Path(p)) for p in (affected_paths or [])],
            )
            rows.append(record)
            self._write(rows)
            return record

    def record_step(self, operation_id: str, step: str) -> OperationRecord:
        if not step.strip():
            raise ValueError("step must not be empty")
        return self._update(operation_id, lambda row: row.completed_steps.append(step))

    def finish(
        self,
        operation_id: str,
        status: str,
        *,
        error: str | None = None,
        recovery_note: str | None = None,
    ) -> OperationRecord:
        if status not in TERMINAL_STATES:
            raise ValueError(f"terminal status required, got: {status}")
        def update(row: OperationRecord) -> None:
            row.status = status
            row.error = error
            row.recovery_note = recovery_note
        return self._update(operation_id, update)

    def _update(self, operation_id: str, change) -> OperationRecord:
        with self._lock:
            rows = self._read()
            for row in rows:
                if row.operation_id == operation_id:
                    if row.status in TERMINAL_STATES:
                        raise ValueError("operation is already terminal")
                    change(row)
                    row.updated_at = _now()
                    self._write(rows)
                    return row
            raise KeyError(f"Unknown operation ID: {operation_id}")

    def list_operations(self) -> list[OperationRecord]:
        with self._lock:
            return self._read()

    def unfinished(self) -> list[OperationRecord]:
        """Return interrupted/in-progress records for explicit user inspection."""
        return [row for row in self.list_operations() if row.status == "in_progress"]

    def acknowledge_recovery(self, operation_id: str, note: str) -> OperationRecord:
        """Mark an interrupted record as reviewed; this does not alter any files."""
        if not note.strip():
            raise ValueError("A recovery note is required")
        return self.finish(
            operation_id, "abandoned",
            error="Operation was interrupted; no automatic resume was attempted.",
            recovery_note=note.strip(),
        )
