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



def test_malformed_manifest_is_rejected(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"audio")
    backup = create_verified_backup(library, tmp_path / "backups").path
    manifest = backup / ".music-sync-backup.json"
    manifest.write_text('{"format": 99, "backup_id": "x", "files": {}}', encoding="utf-8")

    with pytest.raises(BackupVerificationError, match="manifest is invalid"):
        verify_backup_contents(backup)


def test_rewritten_manifest_is_not_misrepresented_as_authenticity_proof(tmp_path: Path):
    # Integrity checking compares bytes with the local manifest; it cannot authenticate
    # the manifest's author if both the payload and manifest are rewritten together.
    import hashlib
    import json

    library = tmp_path / "library"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"original")
    backup = create_verified_backup(library, tmp_path / "backups").path
    (backup / "song.mp3").write_bytes(b"tampered")
    manifest_path = backup / ".music-sync-backup.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    stat = (backup / "song.mp3").stat()
    payload["files"]["song.mp3"] = {
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": hashlib.sha256(b"tampered").hexdigest(),
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    assert verify_backup_contents(backup).file_count == 1


def test_malformed_manifest_is_rejected(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"audio")
    backup = create_verified_backup(library, tmp_path / "backups").path
    manifest = backup / ".music-sync-backup.json"
    manifest.write_text('{"format": 99, "backup_id": "x", "files": {}}', encoding="utf-8")
    with pytest.raises(BackupVerificationError, match="manifest is invalid"):
        verify_backup_contents(backup)


def test_rewritten_manifest_is_not_authenticity_proof(tmp_path: Path):
    import hashlib
    import json

    library = tmp_path / "library"
    library.mkdir()
    (library / "song.mp3").write_bytes(b"original")
    backup = create_verified_backup(library, tmp_path / "backups").path
    (backup / "song.mp3").write_bytes(b"tampered")
    manifest_path = backup / ".music-sync-backup.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    stat = (backup / "song.mp3").stat()
    payload["files"]["song.mp3"] = {
        "size": stat.st_size, "modified_ns": stat.st_mtime_ns,
        "sha256": hashlib.sha256(b"tampered").hexdigest(),
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert verify_backup_contents(backup).file_count == 1
