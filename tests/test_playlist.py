from pathlib import Path

import pytest

from harmelune.playlist import apply_playlist_repairs, inspect_playlist, suggest_replacements


def test_inspection_is_read_only_and_finds_missing_paths(tmp_path: Path):
    music = tmp_path / "Music"
    music.mkdir()
    existing = music / "present.flac"
    existing.write_bytes(b"audio")
    playlist = music / "mix.m3u8"
    original = "#EXTM3U\npresent.flac\nmissing.flac\n"
    playlist.write_text(original, encoding="utf-8")

    report = inspect_playlist(playlist)

    assert len(report.entries) == 2
    assert report.entries[0].exists
    assert [entry.raw_path for entry in report.missing] == ["missing.flac"]
    assert playlist.read_text(encoding="utf-8") == original


def test_only_unique_basename_replacements_are_suggested(tmp_path: Path):
    playlist = tmp_path / "mix.m3u"
    playlist.write_text("missing.flac\nambiguous.flac\n", encoding="utf-8")
    report = inspect_playlist(playlist)
    one = tmp_path / "one" / "missing.flac"
    one.parent.mkdir()
    one.write_bytes(b"one")
    a = tmp_path / "a" / "ambiguous.flac"
    b = tmp_path / "b" / "ambiguous.flac"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    suggestions = suggest_replacements(report, [one, a, b])

    assert suggestions == {1: one.resolve()}


def test_repair_creates_backup_and_writes_only_explicit_decisions(tmp_path: Path):
    playlist = tmp_path / "mix.m3u"
    playlist.write_text("#EXTM3U\nmissing.flac\n", encoding="utf-8")
    replacement = tmp_path / "actual.flac"
    replacement.write_bytes(b"audio")
    report = inspect_playlist(playlist)

    apply_playlist_repairs(report, {2: replacement})

    assert playlist.with_suffix(".m3u.bak").read_text(encoding="utf-8") == "#EXTM3U\nmissing.flac\n"
    assert str(replacement.resolve()) in playlist.read_text(encoding="utf-8")


def test_repair_rejects_non_entry_line_and_nonexistent_replacement(tmp_path: Path):
    playlist = tmp_path / "mix.m3u"
    playlist.write_text("#EXTM3U\nmissing.flac\n", encoding="utf-8")
    report = inspect_playlist(playlist)
    with pytest.raises(ValueError, match="not a playlist track entry"):
        apply_playlist_repairs(report, {1: tmp_path / "actual.flac"})
    with pytest.raises(FileNotFoundError):
        apply_playlist_repairs(report, {2: tmp_path / "absent.flac"})


def test_unsupported_extension_and_invalid_utf8_are_reported(tmp_path: Path):
    with pytest.raises(ValueError, match="Only .m3u"):
        inspect_playlist(tmp_path / "playlist.txt")
    playlist = tmp_path / "bad.m3u8"
    playlist.write_bytes(b"\xff\xfe")
    report = inspect_playlist(playlist)
    assert report.errors and "UTF-8" in report.errors[0]
