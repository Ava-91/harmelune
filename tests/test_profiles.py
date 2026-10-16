from pathlib import Path

import pytest

from harmelune.profiles import ProfileStore, ProfileStoreError
from harmelune.settings import Settings


def test_profile_round_trip_and_unicode_paths(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles.json")
    settings = Settings(library_a="E:/音楽/主要", library_b="F:/音乐", master="library_b", sync_mode="safe")
    store.save("USB 音乐", settings)

    assert store.names() == ["USB 音乐"]
    assert store.load("USB 音乐") == settings
    assert ProfileStore(store.path).load("USB 音乐").library_a == "E:/音楽/主要"


def test_profile_names_are_case_insensitive_and_can_be_renamed(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles.json")
    store.save("Phone", Settings())
    with pytest.raises(ValueError, match="already exists"):
        store.save("phone", Settings())
    store.save("PHONE", Settings(library_a="D:/Music"), overwrite=True)
    assert store.names() == ["PHONE"]
    assert store.load("PHONE").library_a == "D:/Music"


def test_invalid_settings_are_rejected_before_save(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles.json")
    with pytest.raises(ValueError):
        store.save("invalid", Settings(fuzzy_threshold=3.0))
    with pytest.raises(ValueError):
        store.save(" ", Settings())


def test_corrupt_profile_file_is_preserved(tmp_path: Path):
    path = tmp_path / "profiles.json"
    path.write_text("{broken", encoding="utf-8")
    store = ProfileStore(path)
    with pytest.raises(ProfileStoreError):
        store.save("new", Settings())
    assert path.read_text(encoding="utf-8") == "{broken"


def test_delete_profile(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles.json")
    store.save("USB", Settings())
    store.delete("USB")
    assert store.names() == []
