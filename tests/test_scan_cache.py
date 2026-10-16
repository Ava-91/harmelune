from pathlib import Path

from harmelune.cache import ScanCache


def record(digest: str = "a" * 64):
    return {
        "file_hash": digest,
        "title": "Title",
        "artist": "Artist",
        "album": "Album",
        "duration": 123.4,
        "artwork_hashes": ["b" * 64],
    }


def test_cache_round_trip_and_hash_validation(tmp_path: Path):
    store = ScanCache(tmp_path / "cache.json")
    store.load()
    store.put("album/song.flac", record())
    store.save()

    reopened = ScanCache(store.path)
    reopened.load()
    assert reopened.get("album/song.flac", "a" * 64)["title"] == "Title"
    assert reopened.get("album/song.flac", "c" * 64) is None


def test_corrupt_cache_is_discarded_and_never_trusted(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text("{broken", encoding="utf-8")
    store = ScanCache(path)
    assert store.load() == {}
    assert store.cache_was_reset
    assert store.get("song.flac", "a" * 64) is None


def test_disabled_cache_never_reads_or_writes(tmp_path: Path):
    path = tmp_path / "cache.json"
    store = ScanCache(path, enabled=False)
    store.load()
    store.put("song.flac", record())
    store.save()
    assert not path.exists()
    assert store.get("song.flac", "a" * 64) is None


def test_prune_removes_paths_not_seen_in_complete_scan(tmp_path: Path):
    store = ScanCache(tmp_path / "cache.json")
    store.load()
    store.put("keep.flac", record())
    store.put("removed.flac", record("c" * 64))
    store.prune({"keep.flac"})
    assert list(store.entries) == ["keep.flac"]


def test_rejects_malformed_record(tmp_path: Path):
    store = ScanCache(tmp_path / "cache.json")
    store.load()
    try:
        store.put("song.flac", {"file_hash": "bad"})
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("malformed cache record was accepted")


def test_scanner_reuses_tags_only_when_content_hash_matches(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from harmelune import scanner
    from harmelune.artwork_hash import ArtworkInfo

    root = tmp_path / "Music"
    root.mkdir()
    song = root / "song.mp3"
    song.write_bytes(b"audio-one")
    monkeypatch.setattr(scanner, "default_config_dir", lambda: tmp_path / "config")
    calls = {"count": 0}

    class FakeAudio:
        tags = {"title": ["Cached title"], "artist": ["Artist"], "album": ["Album"]}
        info = SimpleNamespace(length=42.0)

    def fake_file(*_args, **_kwargs):
        calls["count"] += 1
        return FakeAudio()

    monkeypatch.setattr(scanner, "File", fake_file)
    monkeypatch.setattr(scanner, "extract_artwork_info", lambda _path: ArtworkInfo(1, ("b" * 64,)))

    first = scanner.scan_library(root, "a")
    assert first.tracks[0].title == "Cached title"
    assert calls["count"] == 2

    second = scanner.scan_library(root, "a")
    assert second.tracks[0].title == "Cached title"
    assert calls["count"] == 2

    song.write_bytes(b"audio-two")
    third = scanner.scan_library(root, "a")
    assert third.tracks[0].title == "Cached title"
    assert calls["count"] == 4


def test_scanner_can_disable_cache(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from harmelune import scanner
    from harmelune.artwork_hash import ArtworkInfo

    root = tmp_path / "Music"
    root.mkdir()
    (root / "song.mp3").write_bytes(b"audio")
    monkeypatch.setattr(scanner, "default_config_dir", lambda: tmp_path / "config")
    calls = {"count": 0}
    class FakeAudio:
        tags = {"title": ["Title"]}
        info = SimpleNamespace(length=1.0)
    def fake_file(*_args, **_kwargs):
        calls["count"] += 1
        return FakeAudio()
    monkeypatch.setattr(scanner, "File", fake_file)
    monkeypatch.setattr(scanner, "extract_artwork_info", lambda _path: ArtworkInfo(0, ()))

    scanner.scan_library(root, "a", use_cache=False)
    scanner.scan_library(root, "a", use_cache=False)
    assert calls["count"] == 4
