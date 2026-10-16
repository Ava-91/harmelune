from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .sync import make_backup
from .backup import MANIFEST_NAME, restore_verified_backup


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    created_at: datetime
    file_count: int
    size_bytes: int


def _stats(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for path in root.rglob("*"):
        if path.is_file() and path.name != MANIFEST_NAME:
            count += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
    return count, size


def list_backups(backup_root: Path) -> list[BackupInfo]:
    """List valid Harmelune backup directories, newest first."""
    if not backup_root.is_dir():
        return []
    backups: list[BackupInfo] = []
    for path in backup_root.iterdir():
        if not path.is_dir() or not path.name.startswith("music_backup_"):
            continue
        stamp = path.name.removeprefix("music_backup_")
        created = None
        for pattern in ("%Y%m%d_%H%M%S", "%Y%m%dT%H%M%S%fZ"):
            try:
                created = datetime.strptime(stamp, pattern)
                break
            except ValueError:
                continue
        if created is None:
            continue
        count, size = _stats(path)
        backups.append(BackupInfo(path, created, count, size))
    return sorted(backups, key=lambda item: item.created_at, reverse=True)


def restore_backup(backup: Path, target: Path, backup_root: Path) -> Path:
    """Safely restore a backup after first protecting the current library."""
    backup = backup.resolve()
    target = target.resolve()
    if not backup.is_dir():
        raise FileNotFoundError(f"Backup not found: {backup}")
    if backup == target or backup.is_relative_to(target):
        raise ValueError("Backup cannot be restored into itself.")

    if target.is_dir() and (target == backup or target.is_relative_to(backup)):
        raise ValueError("Restore target cannot be inside the selected backup.")
    if (backup / MANIFEST_NAME).is_file():
        result = restore_verified_backup(backup, target, backup_root, "RESTORE")
        if not result.restored:
            raise RuntimeError(result.error or "Verified restore did not complete.")
        return result.safety_backup or backup_root
    # Compatibility path for older backups without a verification manifest.
    pre_restore = make_backup(target, backup_root) if target.exists() else backup_root / "no-current-library-backup"
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.resolve() == backup_root.resolve():
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(backup, target, dirs_exist_ok=True)
    return pre_restore
