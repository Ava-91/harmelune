from pathlib import Path

import pytest

from harmelune.execution_report import ExecutionReport, ReportStatus
from harmelune.history import HistoryCorruptError, SyncHistoryStore


def report(mode: str = "safe") -> ExecutionReport:
    return ExecutionReport(mode=mode, final_status=ReportStatus.SUCCESS, succeeded=2)


def test_history_persists_and_orders_newest_first(tmp_path: Path):
    store = SyncHistoryStore(tmp_path / "history.json")
    first = store.append(report("safe"))
    second = store.append(report("mirror"))
    reopened = SyncHistoryStore(store.path)

    entries = reopened.list_entries()
    assert [entry["report"]["mode"] for entry in entries] == ["mirror", "safe"]
    assert entries[1]["created_at"] == first["created_at"]
    assert entries[0]["created_at"] == second["created_at"]


def test_history_is_bounded(tmp_path: Path):
    store = SyncHistoryStore(tmp_path / "history.json", limit=2)
    store.append(report("one"))
    store.append(report("two"))
    store.append(report("three"))
    assert [x["report"]["mode"] for x in store.list_entries()] == ["three", "two"]


def test_corrupt_history_is_not_overwritten(tmp_path: Path):
    path = tmp_path / "history.json"
    original = "{truncated"
    path.write_text(original, encoding="utf-8")
    store = SyncHistoryStore(path)
    with pytest.raises(HistoryCorruptError):
        store.append(report())
    assert path.read_text(encoding="utf-8") == original


def test_clear_removes_records_only(tmp_path: Path):
    library = tmp_path / "Music"
    library.mkdir()
    song = library / "track.flac"
    song.write_bytes(b"preserve")
    store = SyncHistoryStore(tmp_path / "history.json")
    store.append(report())
    store.clear()
    assert store.list_entries() == []
    assert song.read_bytes() == b"preserve"


def test_history_rejects_invalid_limit(tmp_path: Path):
    with pytest.raises(ValueError):
        SyncHistoryStore(tmp_path / "history.json", limit=0)
