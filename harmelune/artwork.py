from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4

from PIL import Image, ImageTk
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover


def extract_first_artwork(path: Path) -> bytes | None:
    """Return the first embedded artwork image from an audio file."""
    audio = File(path, easy=False)
    if not audio:
        return None

    for key, value in (audio.tags or {}).items():
        if str(key).upper().startswith("APIC"):
            data = getattr(value, "data", None)
            if data:
                return bytes(data)
        if str(key).upper() == "COVR":
            try:
                return bytes(value[0]) if value else None
            except (TypeError, IndexError):
                return None

    pictures = getattr(audio, "pictures", []) or []
    if pictures:
        data = getattr(pictures[0], "data", None)
        if data:
            return bytes(data)
    return None


def make_preview(path: Path, size: tuple[int, int] = (180, 180)) -> ImageTk.PhotoImage | None:
    """Build a Tk-compatible artwork preview, returning None when unavailable."""
    data = extract_first_artwork(path)
    if not data:
        return None
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)
    except Exception:
        return None


SUPPORTED_ARTWORK_AUDIO = {".mp3", ".flac", ".m4a", ".m4b"}


class ArtworkRepairError(RuntimeError):
    """Artwork could not be written or safely rolled back."""


def make_image_preview(path: Path, size: tuple[int, int] = (180, 180)) -> ImageTk.PhotoImage | None:
    """Build a Tk-compatible preview from a candidate JPEG/PNG image."""
    try:
        image = Image.open(path).convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)
    except Exception:
        return None


def replace_artwork(audio_path: Path, image_path: Path, backup_dir: Path) -> Path:
    """Replace embedded artwork for MP3, FLAC, or M4A/M4B after a full-file backup."""
    audio_path = Path(audio_path).expanduser().resolve(strict=True)
    image_path = Path(image_path).expanduser().resolve(strict=True)
    suffix = audio_path.suffix.lower()
    if suffix not in SUPPORTED_ARTWORK_AUDIO:
        raise ValueError(f"Artwork replacement is not supported for {suffix or 'this file type'}.")
    if not audio_path.is_file() or not image_path.is_file():
        raise ValueError("Both the audio file and artwork image must be regular files.")

    try:
        with Image.open(image_path) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
        if image_format not in {"JPEG", "PNG"}:
            raise ValueError("Artwork must be a JPEG or PNG image.")
        payload = image_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError(f"Artwork image is invalid or unsupported: {exc}") from exc

    backup_root = Path(backup_dir).expanduser().resolve(strict=False)
    parent = audio_path.parent.resolve()
    if backup_root == parent or backup_root.is_relative_to(parent) or parent.is_relative_to(backup_root):
        raise ValueError("Artwork backup location must be separate from the audio folder.")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{audio_path.name}.{uuid4().hex}.bak"
    shutil.copy2(audio_path, backup)

    try:
        if suffix == ".mp3":
            try:
                tags = ID3(audio_path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("APIC")
            tags.add(APIC(
                encoding=3, mime="image/jpeg" if image_format == "JPEG" else "image/png",
                type=3, desc="Cover", data=payload,
            ))
            tags.save(audio_path)
        elif suffix == ".flac":
            audio = FLAC(audio_path)
            audio.clear_pictures()
            picture = Picture()
            picture.type = 3
            picture.mime = "image/jpeg" if image_format == "JPEG" else "image/png"
            picture.desc = "Cover"
            picture.width = width
            picture.height = height
            picture.depth = 24
            picture.data = payload
            audio.add_picture(picture)
            audio.save()
        else:
            audio = MP4(audio_path)
            if audio.tags is None:
                audio.add_tags()
            image_format_value = MP4Cover.FORMAT_JPEG if image_format == "JPEG" else MP4Cover.FORMAT_PNG
            audio.tags["covr"] = [MP4Cover(payload, imageformat=image_format_value)]
            audio.save()
    except Exception as exc:
        try:
            shutil.copy2(backup, audio_path)
        except OSError as recovery_exc:
            raise ArtworkRepairError(
                f"Artwork update failed ({exc}); automatic recovery also failed ({recovery_exc}). "
                f"Restore the original audio file manually from {backup}."
            ) from recovery_exc
        raise ArtworkRepairError(
            f"Artwork update failed and the original file was restored from {backup}: {exc}"
        ) from exc
    return backup
