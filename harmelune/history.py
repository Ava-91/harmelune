from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HistoryCorruptError(RuntimeError):
    """Raised rather than overwriting an unreadable history file."""


class SyncHistoryStore:
    """A bounded local index of operation reports, not an undo system."""

    FORMAT = 1

    def __init__(self, path: str | Path, *, limit: int = 100) -> None:
        if limit < 1:
            raise ValueError("history limit must be positive")
        self.path = Path(path)
        self.limit = limit
        self._lock = threading.RLock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != self.FORMAT:
                raise ValueError("unsupported history format")
            entries = payload.get("entries")
            if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                raise ValueError("history entries must be objects")
            for item in entries:
                if not isinstance(item.get("created_at"), str) or not isinstance(item.get("report"), dict):
                    raise ValueError("history entry is missing required fields")
            return entries
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HistoryCorruptError(
                f"Sync history cannot be read safely: {self.path}. Preserve it for inspection."
            ) from exc

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": self.FORMAT, "entries": entries[-self.limit:]}
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def append(self, report: Any) -> dict[str, Any]:
        data = report.to_dict() if hasattr(report, "to_dict") else report
        if not isinstance(data, dict):
            raise TypeError("report must be a mapping or expose to_dict()")
        entry = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "report": data}
        with self._lock:
            entries = self._read()
            entries.append(entry)
            self._write(entries)
        return entry

    def list_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._read()))

    def clear(self) -> None:
        """Clear history only; this does not change music files or backups."""
        with self._lock:
            self._write([])
