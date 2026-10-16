from pathlib import Path

from harmelune.scanner import current_fingerprint, scan_library


def test_current_fingerprint_supports_unicode_and_spaces(tmp_path: Path):
    root = tmp_path / "Library A – 夜" / "My Music"
    root.mkdir(parents=True)
    track = root / "Björk" / "Jóga.mp3"
    track.parent.mkdir()
    track.write_bytes(b"test audio")

    fingerprint = current_fingerprint(root)

    key = str(track.relative_to(root))
    assert key in fingerprint
    assert fingerprint[key].size == len(b"test audio")
    assert fingerprint[key].modified_ns > 0



def test_scan_counts_unsupported_audio_like_files_without_second_traversal(tmp_path: Path):
    (tmp_path / "album.aiff").write_bytes(b"unsupported format")
    (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")

    result = scan_library(tmp_path, "a")

    assert result.unsupported_audio_files == 1
    assert result.enumeration_complete is True


def test_scan_cancellation_is_explicit_and_marks_inventory_incomplete(tmp_path: Path):
    (tmp_path / "song.mp3").write_bytes(b"audio")

    result = scan_library(tmp_path, "a", cancel=lambda: True)

    assert result.enumeration_complete is False
    assert "Scan cancelled by user" in result.errors
