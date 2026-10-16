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
