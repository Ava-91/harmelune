from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .settings import Settings


class ProfileStoreError(RuntimeError):
    """Raised when profile data cannot be safely loaded or written."""


class ProfileStore:
    FORMAT = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != self.FORMAT:
                raise ValueError("unsupported profile format")
            profiles = payload.get("profiles")
            if not isinstance(profiles, dict):
                raise ValueError("profiles must be an object")
            clean: dict[str, dict] = {}
            for name, data in profiles.items():
                if not isinstance(name, str) or not name.strip() or not isinstance(data, dict):
                    raise ValueError("invalid profile entry")
                settings = Settings(**data)
                settings.validate()
                clean[name] = asdict(settings)
            return clean
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ProfileStoreError(f"Profiles cannot be read safely: {self.path}. Preserve the file for inspection.") from exc

    def _write(self, profiles: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"format": self.FORMAT, "profiles": profiles}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def names(self) -> list[str]:
        return sorted(self._read(), key=str.casefold)

    def save(self, name: str, settings: Settings, *, overwrite: bool = False) -> None:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Profile name must contain 1–80 characters.")
        settings.validate()
        profiles = self._read()
        existing = next((item for item in profiles if item.casefold() == name.casefold()), None)
        if existing is not None and not overwrite:
            raise ValueError(f"A profile named {existing!r} already exists.")
        if existing is not None and existing != name:
            del profiles[existing]
        profiles[name] = asdict(settings)
        self._write(profiles)

    def load(self, name: str) -> Settings:
        profiles = self._read()
        if name not in profiles:
            raise KeyError(f"Unknown synchronization profile: {name}")
        settings = Settings(**profiles[name])
        settings.validate()
        return settings

    def delete(self, name: str) -> None:
        profiles = self._read()
        if name not in profiles:
            raise KeyError(f"Unknown synchronization profile: {name}")
        del profiles[name]
        self._write(profiles)
