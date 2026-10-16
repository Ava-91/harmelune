from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil

MANIFEST_NAME = ".music-sync-backup.json"


class BackupVerificationError(RuntimeError):
    """Raised when a backup does not exactly match the source snapshot."""


class RestoreConfirmationError(RuntimeError):
    """Raised when restore is not explicitly confirmed."""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    backup_id: str
    file_count: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored: bool
    recovered: bool
    safety_backup: Path | None
    error: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_for(root: Path) -> dict[str, dict[str, int | str]]:
    manifest: dict[str, dict[str, int | str]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        stat = path.stat()
        relative = str(path.relative_to(root))
        manifest[relative] = {
            "size": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "sha256": _sha256(path),
        }
    return manifest


def _load_manifest(backup: Path) -> tuple[str, dict[str, dict[str, int | str]]]:
    manifest_path = backup / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BackupVerificationError(f"Backup manifest is missing: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != 1:
            raise ValueError("Unsupported manifest format")
        backup_id = payload.get("backup_id")
        files = payload.get("files")
        if not isinstance(backup_id, str) or not backup_id or not isinstance(files, dict):
            raise ValueError("Invalid backup identity or file map")
        for relative, entry in files.items():
            relative_path = Path(relative)
            if (
                not isinstance(relative, str) or not relative
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative_path.name == MANIFEST_NAME
                or not isinstance(entry, dict)
                or not isinstance(entry.get("size"), int) or entry["size"] < 0
                or not isinstance(entry.get("modified_ns"), int)
                or not isinstance(entry.get("sha256"), str)
                or len(entry["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in entry["sha256"].lower())
            ):
                raise ValueError("Invalid manifest file entry")
        return backup_id, files
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BackupVerificationError(f"Backup manifest is invalid: {manifest_path}") from exc


def _write_manifest(root: Path, backup_id: str, entries: dict[str, dict[str, int | str]]) -> None:
    payload = {
        "format": 1,
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    (root / MANIFEST_NAME).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_backup_contents(backup: Path) -> BackupInfo:
    """Check backup integrity against its co-located manifest; this does not prove authenticity."""
    backup = backup.resolve()
    backup_id, expected = _load_manifest(backup)
    actual = _manifest_for(backup)
    if set(expected) != set(actual):
        raise BackupVerificationError("Backup contents do not match the stored manifest.")
    for relative, entry in expected.items():
        if actual[relative] != entry:
            raise BackupVerificationError(f"Backup verification failed for {relative}.")
    return BackupInfo(backup, backup_id, len(actual), sum(int(item["size"]) for item in actual.values()))


def verify_backup(source: Path, backup: Path) -> BackupInfo:
    """Compare backup integrity with the source using file sets, sizes, mtimes, and SHA-256."""
    source = source.resolve()
    backup = backup.resolve()
    backup_id, entries = _load_manifest(backup)
    source_entries = _manifest_for(source)
    backup_entries = _manifest_for(backup)
    if set(source_entries) != set(entries) or set(source_entries) != set(backup_entries):
        raise BackupVerificationError("Backup file set does not match the source snapshot.")

    for relative, expected in source_entries.items():
        actual = backup_entries[relative]
        if actual != expected or entries[relative] != expected:
            raise BackupVerificationError(f"Backup verification failed for {relative}.")

    return BackupInfo(backup, backup_id, len(source_entries), sum(int(item["size"]) for item in source_entries.values()))


def create_verified_backup(source: Path, backup_root: Path) -> BackupInfo:
    """Copy a library and verify the resulting backup before returning it."""
    source = source.resolve()
    backup_root = backup_root.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Library not found: {source}")
    if source == backup_root or source.is_relative_to(backup_root) or backup_root.is_relative_to(source):
        raise ValueError("Backup location must be outside the source library.")

    backup_root.mkdir(parents=True, exist_ok=True)
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_root / f"music_backup_{backup_id}"
    shutil.copytree(source, destination)
    entries = _manifest_for(source)
    _write_manifest(destination, backup_id, entries)
    try:
        return verify_backup(source, destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _restore_directory(target: Path, backup: Path) -> None:
    for child in target.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in backup.iterdir():
        if child.name == MANIFEST_NAME:
            continue
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def restore_verified_backup(
    backup: Path,
    target: Path,
    safety_backup_root: Path,
    confirmation: str,
) -> RestoreResult:
    """Restore a verified backup only after exact RESTORE confirmation."""
    if confirmation != "RESTORE":
        raise RestoreConfirmationError("Restore requires exact confirmation text: RESTORE")

    backup = backup.resolve()
    target = target.resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"Restore target is not an existing directory: {target}")
    verify_backup_contents(backup)
    safety = create_verified_backup(target, safety_backup_root).path

    try:
        _restore_directory(target, backup)
        verify_backup(target, backup)
        return RestoreResult(True, True, safety)
    except Exception as exc:
        try:
            _restore_directory(target, safety)
            verify_backup(target, safety)
            return RestoreResult(False, True, safety, str(exc))
        except Exception as recovery_exc:
            return RestoreResult(False, False, safety, f"Restore failed: {exc}; recovery failed: {recovery_exc}")
