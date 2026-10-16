from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from mutagen import File


FIELDS = ("title", "artist", "album", "tracknumber")


class MetadataRepairError(RuntimeError):
    """Metadata could not be written or safely rolled back."""


def inspect_metadata(path: str | Path) -> dict[str, str]:
    """Read the supported common tags without modifying the audio file."""
    path = Path(path).expanduser().resolve(strict=True)
    audio = File(path, easy=True)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio format: {path}")
    tags = audio.tags or {}
    result: dict[str, str] = {}
    for field in FIELDS:
        value = tags.get(field, "")
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        result[field] = str(value or "")
    return result


def repair_metadata(
    path: str | Path,
    updates: dict[str, str],
    backup_dir: str | Path,
) -> Path:
    """Apply explicit tag edits after making a full-file backup.

    Blank values remove a supported tag. A failed save attempts to restore the
    original bytes and reports the backup location if manual recovery is needed.
    """
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    unknown = set(updates) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unsupported metadata fields: {', '.join(sorted(unknown))}")
    normalized = {key: str(value).strip() for key, value in updates.items()}
    if not normalized:
        raise ValueError("No metadata changes were supplied.")
    if all(value == str(inspect_metadata(path).get(key, "")).strip() for key, value in normalized.items()):
        raise ValueError("The proposed metadata is unchanged.")

    backup_root = Path(backup_dir).expanduser().resolve(strict=False)
    parent = path.parent.resolve()
    if backup_root == parent or backup_root.is_relative_to(parent) or parent.is_relative_to(backup_root):
        raise ValueError("Metadata backup location must be separate from the audio folder.")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{path.name}.{uuid4().hex}.bak"
    shutil.copy2(path, backup)

    try:
        audio = File(path, easy=True)
        if audio is None:
            raise ValueError(f"Unsupported or unreadable audio format: {path}")
        if audio.tags is None:
            audio.add_tags()
        for key, value in normalized.items():
            if value:
                audio[key] = [value]
            elif key in audio:
                del audio[key]
        audio.save()
    except Exception as exc:
        try:
            shutil.copy2(backup, path)
        except OSError as recovery_exc:
            raise MetadataRepairError(
                f"Metadata update failed ({exc}); automatic recovery also failed ({recovery_exc}). "
                f"Restore the original file manually from {backup}."
            ) from recovery_exc
        raise MetadataRepairError(
            f"Metadata update failed and the original file was restored from {backup}: {exc}"
        ) from exc
    return backup
