from __future__ import annotations

from pathlib import Path

import pytest

from harmelune.backup import create_verified_backup, verify_backup_contents
from harmelune.direction import MasterLibrary, SyncDirection
from harmelune.mirror import build_mirror_preview, execute_mirror
from harmelune.models import SyncPlan, Track
from harmelune.reconcile import ReconcileDecision, execute_reconcile
from harmelune.scanner import current_fingerprint
from harmelune.sync import execute_safe


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def fresh_plan(a: Path, b: Path, **kwargs) -> SyncPlan:
    return SyncPlan(
        library_a_root=a,
        library_b_root=b,
        fingerprint_a=current_fingerprint(a),
        fingerprint_b=current_fingerprint(b),
        **kwargs,
    )


def test_safe_lifecycle_preserves_existing_destination_and_verifies_backup(tmp_path: Path):
    a, b, backups = tmp_path / "A", tmp_path / "B", tmp_path / "Backups"
    a.mkdir()
    b.mkdir()
    (a / "new.mp3").write_bytes(b"new-track")
    (b / "keep.mp3").write_bytes(b"destination-original")
    before = snapshot(b)
    plan = fresh_plan(a, b, library_a_only=[Track(a / "new.mp3", "a")])

    result = execute_safe(plan, SyncDirection(a, b, MasterLibrary.LIBRARY_A), backups)

    assert result.status == "SUCCESS"
    assert snapshot(b) == {**before, "new.mp3": b"new-track"}
    assert result.backup is not None
    verify_backup_contents(result.backup)


def test_reconcile_lifecycle_requires_explicit_copy_decision(tmp_path: Path):
    a, b, backups = tmp_path / "A", tmp_path / "B", tmp_path / "Backups"
    a.mkdir()
    b.mkdir()
    source = a / "song.mp3"
    source.write_bytes(b"source-track")
    before_a = snapshot(a)
    plan = fresh_plan(a, b, library_a_only=[Track(source, "a")])

    blocked = execute_reconcile(plan, {}, backups)
    assert blocked.status == "BLOCKED"
    assert snapshot(a) == before_a
    assert snapshot(b) == {}

    # Plans are unchanged because the blocked pass did not modify either library.
    decision = {f"a-only:{source}": ReconcileDecision.COPY_A_TO_B}
    result = execute_reconcile(plan, decision, backups)
    assert result.status == "SUCCESS"
    assert snapshot(a) == before_a
    assert (b / "song.mp3").read_bytes() == b"source-track"
    assert result.backups
    for backup in result.backups.values():
        verify_backup_contents(backup)


def test_mirror_preview_is_read_only_then_confirmed_apply_matches_master(tmp_path: Path):
    a, b, backups = tmp_path / "A", tmp_path / "B", tmp_path / "Backups"
    a.mkdir()
    b.mkdir()
    (a / "keep.mp3").write_bytes(b"master-track")
    (b / "extra.mp3").write_bytes(b"target-only")
    before_a, before_b = snapshot(a), snapshot(b)
    plan = fresh_plan(
        a, b,
        library_a_only=[Track(a / "keep.mp3", "a")],
        library_b_only=[Track(b / "extra.mp3", "b")],
    )
    direction = SyncDirection(a, b, MasterLibrary.LIBRARY_A)

    preview = build_mirror_preview(plan, direction)
    assert not preview.blocked
    assert snapshot(a) == before_a
    assert snapshot(b) == before_b

    result = execute_mirror(plan, direction, backups, "MIRROR")
    assert result.status == "SUCCESS"
    assert snapshot(a) == before_a
    assert snapshot(b) == before_a
    assert result.backup is not None
    verify_backup_contents(result.backup)


def test_transaction_failure_restores_original_filesystem_snapshot(tmp_path: Path, monkeypatch):
    from harmelune import transaction
    from harmelune.transaction import FileOperation, OperationKind, execute_transaction

    library = tmp_path / "Library"
    library.mkdir()
    original = library / "existing.mp3"
    original.write_bytes(b"original")
    backup = create_verified_backup(library, tmp_path / "Backups").path
    source = tmp_path / "source.mp3"
    source.write_bytes(b"replacement")
    before = snapshot(library)

    real_copy2 = transaction.shutil.copy2
    calls = {"count": 0}
    def fail_second_copy(source_path, destination_path):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected destination failure")
        return real_copy2(source_path, destination_path)
    monkeypatch.setattr(transaction.shutil, "copy2", fail_second_copy)

    result = execute_transaction(
        [FileOperation(OperationKind.REPLACE, source, original)],
        {library: backup},
    )

    assert result.status == "FAILED"
    assert result.rolled_back
    assert snapshot(library) == before
