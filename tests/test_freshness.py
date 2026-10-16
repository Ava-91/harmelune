from pathlib import Path
import os
import shutil

import pytest

from harmelune.freshness import StalePlanError, validate_plan_freshness
from harmelune.models import SyncPlan
from harmelune.scanner import current_fingerprint


def make_plan(a: Path, b: Path) -> SyncPlan:
    return SyncPlan(
        library_a_root=a,
        library_b_root=b,
        fingerprint_a=current_fingerprint(a),
        fingerprint_b=current_fingerprint(b),
    )


def make_libraries(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "one.mp3").write_bytes(b"one")
    (b / "two.mp3").write_bytes(b"two")
    return a, b


def test_fresh_plan_is_accepted(tmp_path: Path):
    a, b = make_libraries(tmp_path)
    validate_plan_freshness(make_plan(a, b))


def test_two_empty_libraries_are_a_valid_fresh_plan(tmp_path: Path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    validate_plan_freshness(make_plan(a, b))


def test_empty_and_populated_libraries_are_a_valid_fresh_plan(tmp_path: Path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "one.mp3").write_bytes(b"one")
    validate_plan_freshness(make_plan(a, b))


@pytest.mark.parametrize("mutation", ["add", "delete", "size", "mtime"])
def test_filesystem_change_invalidates_plan(tmp_path: Path, mutation: str):
    a, b = make_libraries(tmp_path)
    plan = make_plan(a, b)
    target = a / "one.mp3"

    if mutation == "add":
        (a / "new.mp3").write_bytes(b"new")
    elif mutation == "delete":
        target.unlink()
    elif mutation == "size":
        target.write_bytes(b"one plus more")
    else:
        stat = target.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    with pytest.raises(StalePlanError, match="Scan both libraries again"):
        validate_plan_freshness(plan)


def test_missing_library_blocks_execution(tmp_path: Path):
    a, b = make_libraries(tmp_path)
    plan = make_plan(a, b)
    shutil.rmtree(b)
    with pytest.raises(StalePlanError, match="unavailable"):
        validate_plan_freshness(plan)


def test_missing_fingerprint_metadata_blocks_execution(tmp_path: Path):
    a, b = make_libraries(tmp_path)
    plan = SyncPlan(library_a_root=a, library_b_root=b)
    with pytest.raises(StalePlanError, match="fingerprints"):
        validate_plan_freshness(plan)



def test_same_size_content_change_with_restored_timestamp_invalidates_plan(tmp_path: Path):
    a, b = make_libraries(tmp_path)
    target = a / "one.mp3"
    plan = make_plan(a, b)
    before = target.stat()
    target.write_bytes(b"two")  # Same length as the original bytes.
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(StalePlanError, match="content changed"):
        validate_plan_freshness(plan)


def test_same_size_content_change_with_restored_timestamp_invalidates_plan(tmp_path: Path):
    a, b = make_libraries(tmp_path)
    target = a / "one.mp3"
    plan = make_plan(a, b)
    before = target.stat()
    target.write_bytes(b"two")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(StalePlanError, match="content changed"):
        validate_plan_freshness(plan)
