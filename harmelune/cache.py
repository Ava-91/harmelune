from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ScanCache:
    """Best-effort metadata cache keyed by relative path and verified content hash."""

    FORMAT = 1
    REQUIRED = {"file_hash", "title", "artist", "album", "duration", "artwork_hashes"}

    def __init__(self, path: str | Path, *, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.entries: dict[str, dict[str, Any]] = {}
        self.cache_was_reset = False

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.enabled:
            self.entries = {}
            return self.entries
        if not self.path.exists():
            self.entries = {}
            return self.entries
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != self.FORMAT:
                raise ValueError("unsupported cache format")
            entries = payload.get("entries")
            if not isinstance(entries, dict):
                raise ValueError("cache entries must be an object")
            validated: dict[str, dict[str, Any]] = {}
            for relative, row in entries.items():
                if not isinstance(relative, str) or not relative or not isinstance(row, dict):
                    raise ValueError("invalid cache entry")
                if not self.REQUIRED.issubset(row):
                    raise ValueError("cache entry is missing required fields")
                if not isinstance(row["file_hash"], str) or len(row["file_hash"]) != 64:
                    raise ValueError("invalid content hash")
                if not all(isinstance(row[key], str) for key in ("title", "artist", "album")):
                    raise ValueError("invalid cached metadata")
                if row["duration"] is not None and not isinstance(row["duration"], (int, float)):
                    raise ValueError("invalid cached duration")
                if not isinstance(row["artwork_hashes"], list) or not all(isinstance(x, str) for x in row["artwork_hashes"]):
                    raise ValueError("invalid artwork hash list")
                validated[relative] = row
            self.entries = validated
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A corrupt cache is disposable. It is never used as authority for a file.
            self.entries = {}
            self.cache_was_reset = True
        return self.entries

    def get(self, relative_path: str, current_hash: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        row = self.entries.get(relative_path)
        if not row or row.get("file_hash") != current_hash:
            return None
        return dict(row)

    def put(self, relative_path: str, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if not relative_path or not self.REQUIRED.issubset(record):
            raise ValueError("cache record is incomplete")
        if not isinstance(record["file_hash"], str) or len(record["file_hash"]) != 64:
            raise ValueError("cache record needs a SHA-256 content hash")
        self.entries[relative_path] = dict(record)

    def prune(self, seen_paths: set[str]) -> None:
        if self.enabled:
            self.entries = {key: value for key, value in self.entries.items() if key in seen_paths}

    def save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"format": self.FORMAT, "entries": self.entries}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def clear(self) -> None:
        self.entries = {}
        if self.enabled:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
