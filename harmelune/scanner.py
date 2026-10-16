from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from mutagen import File

from .artwork_hash import extract_artwork_info
from .hashing import sha256_file
from .models import FileState, ScanResult, Side, Track

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".m4b", ".flac", ".wav", ".ogg", ".opus", ".aac", ".wma"}
AUDIO_LIKE_EXTENSIONS = AUDIO_EXTENSIONS | {
    ".aiff", ".aif", ".ape", ".alac", ".dsf", ".dff", ".ac3", ".mid", ".midi", ".amr", ".3gp",
}


def _first_tag(audio, *names: str) -> str:
    if not audio or not audio.tags:
        return ""
    for name in names:
        value = audio.tags.get(name)
        if value:
            if isinstance(value, (list, tuple)):
                return str(value[0])
            return str(value)
    return ""


def _walk_files(root: Path, errors: list[str], cancel: Callable[[], bool] | None = None):
    """Yield files incrementally and report traversal failures instead of hiding them."""
    def onerror(exc: OSError) -> None:
        errors.append(f"Could not enumerate {getattr(exc, 'filename', root)}: {exc}")

    for directory, dirs, filenames in os.walk(root, onerror=onerror, followlinks=False):
        if cancel and cancel():
            errors.append("Scan cancelled by user")
            return
        # Stable ordering makes reports and tests deterministic.
        dirs.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        for filename in filenames:
            if cancel and cancel():
                errors.append("Scan cancelled by user")
                return
            yield Path(directory) / filename


def scan_library(
    root: str | Path,
    side: Side,
    progress: Callable[[int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ScanResult:
    """Incrementally scan a library; cancellation and traversal errors are explicit."""
    root = Path(root).expanduser().resolve(strict=False)
    result = ScanResult(side=side, root=root)
    if not root.exists():
        result.errors.append(f"Directory does not exist: {root}")
        result.enumeration_complete = False
        return result
    if not root.is_dir():
        result.errors.append(f"Not a directory: {root}")
        result.enumeration_complete = False
        return result

    processed = 0
    error_count_before = len(result.errors)
    for path in _walk_files(root, result.errors, cancel):
        if cancel and cancel():
            if not result.errors or result.errors[-1] != "Scan cancelled by user":
                result.errors.append("Scan cancelled by user")
            break
        suffix = path.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            if suffix in AUDIO_LIKE_EXTENSIONS:
                result.unsupported_audio_files += 1
            continue
        processed += 1
        try:
            stat = path.stat()
            easy_audio = File(path, easy=True)
            raw_audio = File(path, easy=False)
            duration = float(raw_audio.info.length) if raw_audio and raw_audio.info else None
            artwork = extract_artwork_info(path)
            relative = str(path.relative_to(root))
            file_hash = sha256_file(path)
            result.tracks.append(
                Track(
                    path, side, _first_tag(easy_audio, "title"),
                    _first_tag(easy_audio, "artist", "albumartist"),
                    _first_tag(easy_audio, "album"), duration, stat.st_size,
                    stat.st_mtime_ns, file_hash, artwork.primary_hash, artwork.hashes,
                )
            )
            result.fingerprint[relative] = FileState(relative, stat.st_size, stat.st_mtime_ns, file_hash)
        except (OSError, ValueError, TypeError) as exc:
            result.errors.append(f"Could not read {path}: {exc}")
        except Exception as exc:
            result.errors.append(f"Could not parse {path}: {exc}")
        if progress:
            progress(processed)

    result.enumeration_complete = not any(
        error == "Scan cancelled by user" or error.startswith("Could not enumerate ")
        for error in result.errors
    )
    if len(result.errors) > error_count_before:
        result.enumeration_complete = result.enumeration_complete and not any(
            error.startswith("Could not enumerate ") for error in result.errors
        )
    return result


def current_fingerprint(root: str | Path) -> dict[str, FileState]:
    """Return a content-aware fingerprint; fail closed on any traversal/stat/hash error."""
    root = Path(root).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise FileNotFoundError(f"Library directory is unavailable: {root}")
    fingerprint: dict[str, FileState] = {}
    errors: list[str] = []
    for path in _walk_files(root, errors):
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        stat = path.stat()
        relative = str(path.relative_to(root))
        fingerprint[relative] = FileState(relative, stat.st_size, stat.st_mtime_ns, sha256_file(path))
    if errors:
        raise OSError("; ".join(errors))
    return fingerprint
