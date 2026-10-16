from pathlib import Path

import pytest

from harmelune.backup import BackupVerificationError, create_verified_backup, verify_backup_contents
from harmelune.backups import list_backups, restore_backup


def test_new_verified_backup_format_is_discoverable_and_verifiable(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"audio")
    backup_root = tmp_path / "backups"

    created = create_verified_backup(library, backup_root)
    listed = list_backups(backup_root)

    assert [item.path for item in listed] == [created.path]
    assert listed[0].file_count == 1
    verified = verify_backup_contents(created.path)
    assert verified.file_count == 1
    assert verified.size_bytes == len(b"audio")


def test_modified_verified_backup_fails_integrity_check(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"original")
    backup = create_verified_backup(library, tmp_path / "backups").path
    (backup / "song.mp3").write_bytes(b"tampered")

    with pytest.raises(BackupVerificationError):
        verify_backup_contents(backup)


def test_restore_verified_backup_uses_a_protective_snapshot(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "old.mp3").write_bytes(b"old")
    backup_root = tmp_path / "backups"
    source = tmp_path / "source"
    source.mkdir()
    (source / "new.mp3").write_bytes(b"new")
    snapshot = create_verified_backup(source, backup_root).path

    protection = restore_backup(snapshot, library, backup_root)

    assert (library / "new.mp3").read_bytes() == b"new"
    assert not (library / "old.mp3").exists()
    assert protection.is_dir()
    assert (protection / "old.mp3").read_bytes() == b"old"
