from pathlib import Path

import pytest

from harmelune.relink import relink_settings, unavailable_libraries
from harmelune.settings import Settings


def test_unavailable_roots_are_reported_without_guessing(tmp_path: Path):
    good = tmp_path / "Good"
    good.mkdir()
    assert unavailable_libraries(str(good), str(tmp_path / "missing")) == ("library_b",)
    assert unavailable_libraries("", "") == ("library_a", "library_b")


def test_relink_updates_only_paths_after_both_roots_validate(tmp_path: Path):
    a, b = tmp_path / "New A", tmp_path / "New B"
    a.mkdir()
    b.mkdir()
    original = Settings(
        library_a="Z:/removed/A",
        library_b="Z:/removed/B",
        master="library_b",
        sync_mode="safe",
        backup_location="D:/Backups",
        fuzzy_threshold=0.91,
        appearance="dark",
    )

    updated = relink_settings(original, str(a), str(b))

    assert updated.library_a == str(a.resolve())
    assert updated.library_b == str(b.resolve())
    assert updated.master == original.master
    assert updated.sync_mode == original.sync_mode
    assert updated.backup_location == original.backup_location
    assert updated.fuzzy_threshold == original.fuzzy_threshold
    assert updated.appearance == original.appearance
    assert original.library_a == "Z:/removed/A"


def test_relink_rejects_same_nested_or_missing_roots(tmp_path: Path):
    a = tmp_path / "Library"
    a.mkdir()
    nested = a / "Nested"
    nested.mkdir()
    with pytest.raises(ValueError, match="different directories|contain one another"):
        relink_settings(Settings(), str(a), str(a))
    with pytest.raises(ValueError, match="contain one another"):
        relink_settings(Settings(), str(a), str(nested))
    with pytest.raises(FileNotFoundError):
        relink_settings(Settings(), str(a), str(tmp_path / "missing"))
