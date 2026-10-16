from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from mutagen import File

from .artwork_hash import extract_artwork_info
from .cache import ScanCache
from .hashing import sha256_file
from .models import FileState, ScanResult, Side, Track
from .settings import default_config_dir

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
    use_cache: bool = True,
) -> ScanResult:
    """Incrementally scan a library; cache reuse requires a matching content hash."""
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

    cache = ScanCache(default_config_dir() / "scan-cache.json", enabled=use_cache)
    cache.load()
    seen_paths: set[str] = set()
    visited = 0
    for path in _walk_files(root, result.errors, cancel):
        if cancel and cancel():
            if not result.errors or result.errors[-1] != "Scan cancelled by user":
                result.errors.append("Scan cancelled by user")
            break
        visited += 1
        suffix = path.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            if suffix in AUDIO_LIKE_EXTENSIONS:
                result.unsupported_audio_files += 1
            if progress:
                progress(visited)
            continue
        try:
            stat = path.stat()
            relative = str(path.relative_to(root))
            file_hash = sha256_file(path)
            seen_paths.add(relative)
            cached = cache.get(relative, file_hash)
            if cached is not None:
                artwork_hashes = tuple(cached["artwork_hashes"])
                track = Track(
                    path, side, cached["title"], cached["artist"], cached["album"],
                    cached["duration"], stat.st_size, stat.st_mtime_ns, file_hash,
                    artwork_hashes[0] if artwork_hashes else None, artwork_hashes,
                )
            else:
                easy_audio = File(path, easy=True)
                raw_audio = File(path, easy=False)
                duration = float(raw_audio.info.length) if raw_audio and raw_audio.info else None
                artwork = extract_artwork_info(path)
                title = _first_tag(easy_audio, "title")
                artist = _first_tag(easy_audio, "artist", "albumartist")
                album = _first_tag(easy_audio, "album")
                track = Track(
                    path, side, title, artist, album, duration, stat.st_size,
                    stat.st_mtime_ns, file_hash, artwork.primary_hash, artwork.hashes,
                )
                cache.put(relative, {
                    "file_hash": file_hash, "title": title, "artist": artist,
                    "album": album, "duration": duration, "artwork_hashes": list(artwork.hashes),
                })
            result.tracks.append(track)
            result.fingerprint[relative] = FileState(relative, stat.st_size, stat.st_mtime_ns, file_hash)
        except (OSError, ValueError, TypeError) as exc:
            result.errors.append(f"Could not read {path}: {exc}")
        except Exception as exc:
            result.errors.append(f"Could not parse {path}: {exc}")
        if progress:
            progress(visited)

    result.enumeration_complete = not any(
        error == "Scan cancelled by user" or error.startswith("Could not enumerate ")
        for error in result.errors
    )
    if result.enumeration_complete and not result.errors:
        cache.prune(seen_paths)
    try:
        cache.save()
    except OSError:
        # Cache failure must not invalidate an otherwise successful read-only scan.
        pass
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
