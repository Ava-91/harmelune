from __future__ import annotations

import wave
from pathlib import Path

import pytest

from harmelune.direction import MasterLibrary, SyncDirection
from harmelune.freshness import StalePlanError
from harmelune.models import SyncMode
from harmelune.services import execute_workflow, preview_workflow, scan_libraries


def write_wav(path: Path, frames: int = 80) -> None:
    """Create a tiny valid PCM WAV fixture; no real music files are needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x00\x00" * frames)


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def libraries(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only in A.wav")
    write_wav(b / "Only in B.wav")
    return a, b


def test_scan_libraries_is_read_only_and_returns_reviewable_plan(libraries):
    a, b = libraries
    before_a, before_b = snapshot(a), snapshot(b)

    result = scan_libraries(a, b, use_cache=False)

    assert result is not None
    assert result.library_a == a.resolve()
    assert result.library_b == b.resolve()
    assert result.scan_a.enumeration_complete and result.scan_b.enumeration_complete
    assert result.plan.library_a_only
    assert result.plan.library_b_only
    assert snapshot(a) == before_a
    assert snapshot(b) == before_b


def test_scan_progress_reports_library_side_and_cancel_is_honored(libraries):
    a, b = libraries
    events: list[tuple[str, int]] = []
    result = scan_libraries(a, b, progress=lambda side, count: events.append((side, count)), use_cache=False)

    assert result is not None
    assert {side for side, _count in events} == {"a", "b"}
    assert all(count >= 1 for _side, count in events)

    cancelled = scan_libraries(a, b, cancel=lambda: True, use_cache=False)
    assert cancelled is None


def test_safe_preview_never_changes_libraries(libraries, tmp_path: Path):
    a, b = libraries
    result = scan_libraries(a, b, use_cache=False)
    assert result is not None
    before_a, before_b = snapshot(a), snapshot(b)
    direction = SyncDirection(a.resolve(), b.resolve(), MasterLibrary.LIBRARY_A)

    preview = preview_workflow(result.plan, SyncMode.SAFE, direction)

    assert not preview.blocked
    assert any(operation.destination.name == "Only in A.wav" for operation in preview.operations)
    assert snapshot(a) == before_a
    assert snapshot(b) == before_b
    assert not (tmp_path / "Backups").exists()


def test_preview_rejects_stale_plan_after_library_changes(libraries):
    a, b = libraries
    result = scan_libraries(a, b, use_cache=False)
    assert result is not None
    (a / "new-after-scan.wav").write_bytes(b"changed")
    direction = SyncDirection(a.resolve(), b.resolve(), MasterLibrary.LIBRARY_A)

    with pytest.raises(StalePlanError):
        preview_workflow(result.plan, SyncMode.SAFE, direction)


def test_reconcile_preview_requires_explicit_decisions(libraries):
    a, b = libraries
    result = scan_libraries(a, b, use_cache=False)
    assert result is not None
    direction = SyncDirection(a.resolve(), b.resolve(), MasterLibrary.LIBRARY_A)

    with pytest.raises(ValueError, match="explicit decision"):
        preview_workflow(result.plan, SyncMode.RECONCILE, direction, backup_root=a.parent / "Backups")


def test_execute_refuses_unsupported_mode_before_touching_libraries(libraries, tmp_path: Path):
    a, b = libraries
    result = scan_libraries(a, b, use_cache=False)
    assert result is not None
    before_a, before_b = snapshot(a), snapshot(b)
    direction = SyncDirection(a.resolve(), b.resolve(), MasterLibrary.LIBRARY_A)

    with pytest.raises(ValueError, match="Unsupported sync mode"):
        execute_workflow(result.plan, "unsafe-mode", direction, tmp_path / "Backups")

    assert snapshot(a) == before_a
    assert snapshot(b) == before_b
    assert not (tmp_path / "Backups").exists()
