from pathlib import Path

import pytest

from harmelune import metadata


class FakeAudio:
    def __init__(self, path: Path):
        self.path = path
        self.tags = {"title": ["Old title"], "artist": ["Artist"], "album": ["Album"], "tracknumber": ["1"]}
        self.fail_save = False

    def add_tags(self):
        self.tags = {}

    def __contains__(self, key):
        return key in self.tags

    def __getitem__(self, key):
        return self.tags[key]

    def __setitem__(self, key, value):
        self.tags[key] = value

    def __delitem__(self, key):
        del self.tags[key]

    def save(self):
        if self.fail_save:
            raise OSError("simulated tag write failure")
        self.path.write_bytes(("|".join(f"{k}={v[0]}" for k, v in self.tags.items())).encode())


def test_inspect_metadata_returns_supported_common_fields(tmp_path: Path, monkeypatch):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"original")
    fake = FakeAudio(path)
    monkeypatch.setattr(metadata, "File", lambda *_args, **_kwargs: fake)

    assert metadata.inspect_metadata(path) == {
        "title": "Old title", "artist": "Artist", "album": "Album", "tracknumber": "1"
    }
    assert path.read_bytes() == b"original"


def test_repair_makes_backup_and_updates_only_requested_tags(tmp_path: Path, monkeypatch):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"original")
    fake = FakeAudio(path)
    monkeypatch.setattr(metadata, "File", lambda *_args, **_kwargs: fake)

    backup = metadata.repair_metadata(path, {"title": "New title", "tracknumber": "02"}, tmp_path.parent / f"{tmp_path.name}-Backups")

    assert backup.read_bytes() == b"original"
    assert b"title=New title" in path.read_bytes()
    assert b"artist=Artist" in path.read_bytes()
    assert b"tracknumber=02" in path.read_bytes()


def test_failed_tag_save_restores_original_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"original")
    fake = FakeAudio(path)
    fake.fail_save = True
    monkeypatch.setattr(metadata, "File", lambda *_args, **_kwargs: fake)

    with pytest.raises(metadata.MetadataRepairError, match="original file was restored"):
        metadata.repair_metadata(path, {"title": "New title"}, tmp_path.parent / f"{tmp_path.name}-Backups")
    assert path.read_bytes() == b"original"


def test_rejects_unknown_fields_empty_changes_and_overlapping_backup(tmp_path: Path, monkeypatch):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"original")
    fake = FakeAudio(path)
    monkeypatch.setattr(metadata, "File", lambda *_args, **_kwargs: fake)
    with pytest.raises(ValueError, match="Unsupported metadata fields"):
        metadata.repair_metadata(path, {"lyrics": "no"}, tmp_path.parent / f"{tmp_path.name}-Backups")
    with pytest.raises(ValueError, match="No metadata changes"):
        metadata.repair_metadata(path, {}, tmp_path.parent / f"{tmp_path.name}-Backups")
    with pytest.raises(ValueError, match="separate"):
        metadata.repair_metadata(path, {"title": "New title"}, tmp_path / "subfolder")


def test_rejects_unchanged_metadata(tmp_path: Path, monkeypatch):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"original")
    fake = FakeAudio(path)
    monkeypatch.setattr(metadata, "File", lambda *_args, **_kwargs: fake)
    with pytest.raises(ValueError, match="unchanged"):
        metadata.repair_metadata(path, {"title": "Old title"}, tmp_path.parent / f"{tmp_path.name}-Backups")
