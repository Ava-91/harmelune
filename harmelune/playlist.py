from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    line_number: int
    raw_path: str
    resolved_path: Path
    exists: bool
    is_absolute: bool


@dataclass(frozen=True, slots=True)
class PlaylistReport:
    playlist: Path
    entries: tuple[PlaylistEntry, ...]
    errors: tuple[str, ...] = ()

    @property
    def missing(self) -> tuple[PlaylistEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.exists)


def inspect_playlist(path: str | Path) -> PlaylistReport:
    """Read an M3U/M3U8 playlist without modifying it."""
    playlist = Path(path).expanduser().resolve(strict=False)
    if playlist.suffix.lower() not in {".m3u", ".m3u8"}:
        raise ValueError("Only .m3u and .m3u8 playlists are supported.")
    try:
        text = playlist.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return PlaylistReport(playlist, (), (f"Playlist is not valid UTF-8: {exc}",))
    except OSError as exc:
        return PlaylistReport(playlist, (), (f"Could not read playlist: {exc}",))

    entries: list[PlaylistEntry] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        # Playlist paths use both slash styles on Windows. On POSIX, preserve
        # backslashes as literal filename characters instead of guessing.
        normalized = value.replace("\\", os.sep) if os.name == "nt" else value
        candidate = Path(normalized).expanduser()
        absolute = candidate.is_absolute()
        resolved = candidate.resolve(strict=False) if absolute else (playlist.parent / candidate).resolve(strict=False)
        entries.append(PlaylistEntry(line_number, value, resolved, resolved.is_file(), absolute))
    return PlaylistReport(playlist, tuple(entries))


def suggest_replacements(
    report: PlaylistReport, candidate_files: list[str | Path]
) -> dict[int, Path]:
    """Suggest a replacement only when a missing entry has one unique basename match."""
    by_name: dict[str, list[Path]] = {}
    for item in candidate_files:
        path = Path(item).expanduser().resolve(strict=False)
        if path.is_file():
            by_name.setdefault(path.name.casefold(), []).append(path)
    suggestions: dict[int, Path] = {}
    for entry in report.missing:
        matches = by_name.get(Path(entry.raw_path.replace("\\", "/")).name.casefold(), [])
        if len(matches) == 1:
            suggestions[entry.line_number] = matches[0]
    return suggestions


def apply_playlist_repairs(
    report: PlaylistReport,
    replacements: dict[int, str | Path],
    *,
    create_backup: bool = True,
) -> Path:
    """Apply explicit line-number repairs after review, preserving a .bak copy."""
    if report.errors:
        raise ValueError("Cannot repair a playlist with read errors.")
    if not replacements:
        return report.playlist
    original_lines = report.playlist.read_text(encoding="utf-8-sig").splitlines()
    entries_by_line = {entry.line_number: entry for entry in report.entries}
    for line_number, replacement in replacements.items():
        if line_number not in entries_by_line:
            raise ValueError(f"Line {line_number} is not a playlist track entry.")
        path = Path(replacement).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Replacement is not a file: {path}")
        original_lines[line_number - 1] = str(path)
    backup = report.playlist.with_suffix(report.playlist.suffix + ".bak")
    if create_backup:
        if backup.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = backup.with_name(f"{backup.name}.{stamp}")
        shutil.copy2(report.playlist, backup)
    fd, temporary = tempfile.mkstemp(prefix=f".{report.playlist.name}.", suffix=".tmp", dir=report.playlist.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(original_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, report.playlist)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return report.playlist
