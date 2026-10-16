from pathlib import Path

import pytest

from harmelune.backup import create_verified_backup
from harmelune.transaction import FileOperation, OperationKind, execute_transaction


def make_backup(root: Path, tmp_path: Path):
    return create_verified_backup(root, tmp_path / "Backups").path


def test_successful_multi_operation_transaction(tmp_path: Path):
    library = tmp_path / "Library"
    library.mkdir()
    (library / "replace.txt").write_text("old")
    (library / "delete.txt").write_text("delete")
    backup = make_backup(library, tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("new")

    operations = [
        FileOperation(OperationKind.REPLACE, source, library / "replace.txt"),
        FileOperation(OperationKind.DELETE, None, library / "delete.txt"),
        FileOperation(OperationKind.COPY, source, library / "copy.txt"),
    ]
    result = execute_transaction(operations, {library: backup})

    assert result.status == "SUCCESS"
    assert (library / "replace.txt").read_text() == "new"
    assert not (library / "delete.txt").exists()
    assert (library / "copy.txt").read_text() == "new"


def test_mid_operation_failure_rolls_back_everything(tmp_path: Path, monkeypatch):
    library = tmp_path / "Library"
    library.mkdir()
    (library / "keep.txt").write_text("original")
    backup = make_backup(library, tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("replacement")

    original_copy2 = __import__("harmelune.transaction", fromlist=["shutil"]).shutil.copy2
    calls = {"count": 0}

    def fail_second_copy(source_path, destination_path):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated copy failure")
        return original_copy2(source_path, destination_path)

    monkeypatch.setattr("harmelune.transaction.shutil.copy2", fail_second_copy)
    operations = [
        FileOperation(OperationKind.REPLACE, source, library / "keep.txt"),
        FileOperation(OperationKind.COPY, source, library / "new.txt"),
    ]
    result = execute_transaction(operations, {library: backup})

    assert result.status == "FAILED"
    assert result.rolled_back is True
    assert result.rollback_failures == []
    assert (library / "keep.txt").read_text() == "original"
    assert not (library / "new.txt").exists()


def test_two_library_transaction_rolls_back_both_libraries(tmp_path: Path, monkeypatch):
    library_a = tmp_path / "A"
    library_b = tmp_path / "B"
    library_a.mkdir()
    library_b.mkdir()
    (library_a / "a.txt").write_text("A original")
    (library_b / "b.txt").write_text("B original")
    backup_a = make_backup(library_a, tmp_path)
    backup_b = make_backup(library_b, tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("changed")

    original_copy2 = __import__("harmelune.transaction", fromlist=["shutil"]).shutil.copy2
    calls = {"count": 0}

    def fail_second(source_path, destination_path):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated second-library failure")
        return original_copy2(source_path, destination_path)

    monkeypatch.setattr("harmelune.transaction.shutil.copy2", fail_second)
    operations = [
        FileOperation(OperationKind.REPLACE, source, library_a / "a.txt"),
        FileOperation(OperationKind.REPLACE, source, library_b / "b.txt"),
    ]
    result = execute_transaction(operations, {library_a: backup_a, library_b: backup_b})

    assert result.status == "FAILED"
    assert result.rolled_back is True
    assert (library_a / "a.txt").read_text() == "A original"
    assert (library_b / "b.txt").read_text() == "B original"


def test_rollback_failure_is_reported(tmp_path: Path, monkeypatch):
    library = tmp_path / "Library"
    library.mkdir()
    (library / "file.txt").write_text("original")
    backup = make_backup(library, tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("changed")

    monkeypatch.setattr("harmelune.transaction._restore_from_backup", lambda *_: (_ for _ in ()).throw(OSError("rollback failed")))
    operations = [FileOperation(OperationKind.REPLACE, source, library / "file.txt")]
    monkeypatch.setattr("harmelune.transaction.shutil.copy2", lambda *_: (_ for _ in ()).throw(OSError("copy failed")))

    result = execute_transaction(operations, {library: backup})

    assert result.status == "PARTIAL"
    assert result.rolled_back is False
    assert result.rollback_failures


def test_rollback_failure_includes_manual_recovery_backup_path(tmp_path: Path, monkeypatch):
    library = tmp_path / "Library"
    library.mkdir()
    (library / "file.txt").write_text("original")
    backup = make_backup(library, tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("changed")
    monkeypatch.setattr("harmelune.transaction._restore_from_backup", lambda *_: (_ for _ in ()).throw(OSError("drive disconnected")))
    monkeypatch.setattr("harmelune.transaction.shutil.copy2", lambda *_: (_ for _ in ()).throw(OSError("copy failed")))
    result = execute_transaction([FileOperation(OperationKind.REPLACE, source, library / "file.txt")], {library: backup})
    assert result.status == "PARTIAL"
    assert str(backup) in result.rollback_failures[0]
    assert "MANUAL RECOVERY REQUIRED" in result.rollback_failures[0]
