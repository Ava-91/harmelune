from __future__ import annotations

import json
from pathlib import Path

import pytest

from harmelune.operation_journal import JournalCorruptError, OperationJournal


def test_journal_records_steps_and_terminal_status(tmp_path: Path):
    store = OperationJournal(tmp_path / "state" / "operations.json")
    record = store.begin(
        "mirror",
        backup_paths=[tmp_path / "backup"],
        affected_paths=[tmp_path / "Library" / "track.flac"],
    )
    store.record_step(record.operation_id, "backup_verified")
    finished = store.finish(record.operation_id, "completed")

    assert finished.status == "completed"
    assert finished.completed_steps == ["backup_verified"]
    assert store.unfinished() == []
    reloaded = OperationJournal(store.path).list_operations()
    assert reloaded[0].operation_id == record.operation_id
    assert reloaded[0].backup_paths == [str(tmp_path / "backup")]


def test_interrupted_record_is_returned_but_never_resumed(tmp_path: Path):
    store = OperationJournal(tmp_path / "operations.json")
    record = store.begin("reconcile", affected_paths=[tmp_path / "Library"])
    reopened = OperationJournal(store.path)

    assert [row.operation_id for row in reopened.unfinished()] == [record.operation_id]
    assert reopened.list_operations()[0].status == "in_progress"


def test_recovery_acknowledgement_requires_a_note_and_does_not_touch_files(tmp_path: Path):
    library = tmp_path / "Library"
    library.mkdir()
    audio = library / "track.flac"
    audio.write_bytes(b"keep me")
    store = OperationJournal(tmp_path / "operations.json")
    record = store.begin("mirror", affected_paths=[audio])

    with pytest.raises(ValueError):
        store.acknowledge_recovery(record.operation_id, "  ")
    reviewed = store.acknowledge_recovery(record.operation_id, "Inspected backup manually")
    assert reviewed.status == "abandoned"
    assert audio.read_bytes() == b"keep me"
    assert store.unfinished() == []


def test_corrupt_journal_is_not_silently_discarded(tmp_path: Path):
    path = tmp_path / "operations.json"
    path.write_text("{truncated", encoding="utf-8")

    with pytest.raises(JournalCorruptError, match="Preserve this file"):
        OperationJournal(path).unfinished()


def test_unknown_status_and_double_finish_are_rejected(tmp_path: Path):
    store = OperationJournal(tmp_path / "operations.json")
    record = store.begin("safe")
    with pytest.raises(ValueError):
        store.finish(record.operation_id, "running")
    store.finish(record.operation_id, "rolled_back")
    with pytest.raises(ValueError, match="already terminal"):
        store.finish(record.operation_id, "completed")


def test_journal_payload_contains_metadata_not_file_contents(tmp_path: Path):
    store = OperationJournal(tmp_path / "operations.json")
    secret_audio_bytes = b"private audio payload"
    audio = tmp_path / "song.flac"
    audio.write_bytes(secret_audio_bytes)
    store.begin("safe", affected_paths=[audio])
    payload = store.path.read_bytes()
    assert secret_audio_bytes not in payload
    assert str(audio).encode('utf-8') in payload
