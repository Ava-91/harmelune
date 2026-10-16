from pathlib import Path

from harmelune.health import build_health_report
from harmelune.models import Match, ScanResult, SyncPlan, Track
from harmelune.scanner import scan_library


def scan(side: str, *tracks: Track, errors: list[str] | None = None) -> ScanResult:
    return ScanResult(side=side, root=Path(side), tracks=list(tracks), errors=errors or [])


def test_empty_libraries_have_safe_percentages():
    report = build_health_report(scan("a"), scan("b"))
    assert report.library_a.track_count == 0
    assert report.library_a.metadata_completeness_pct == 100.0
    assert report.library_a.artwork_coverage_pct == 100.0


def test_metadata_artwork_duplicates_and_scan_errors():
    first = Track(Path("a/one.mp3"), "a", title="One", artist="Artist", album="Album", artwork_hash="cover", file_hash="same")
    second = Track(Path("a/two.mp3"), "a", title="", artist="Artist", album="Album", artwork_hash="", file_hash="same")
    third = Track(Path("a/three.mp3"), "a", title="Three", artist="Artist", album="Album", artwork_hash="cover2", file_hash="unique")

    report = build_health_report(scan("a", first, second, third, errors=["bad file"]), scan("b"))

    health = report.library_a
    assert health.track_count == 3
    assert health.unreadable_files == 1
    assert health.complete_metadata == 2
    assert health.metadata_completeness_pct == 200 / 3
    assert health.artwork_tracks == 2
    assert health.artwork_coverage_pct == 200 / 3
    assert health.duplicate_groups == (("a/one.mp3", "a/two.mp3"),)
    assert health.duplicate_tracks == 2
    assert health.missing_artwork_tracks == 1
    assert health.incomplete_metadata_tracks == 1


def test_plan_conflict_and_fuzzy_counts_are_reported():
    clean = Match(Track(Path("a/clean.mp3"), "a"), Track(Path("b/clean.mp3"), "b"), 1.0, confirmed=True)
    fuzzy = Match(Track(Path("a/fuzzy.mp3"), "a"), Track(Path("b/fuzzy.mp3"), "b"), 0.9, confirmed=False)
    conflict = Match(Track(Path("a/conflict.mp3"), "a"), Track(Path("b/conflict.mp3"), "b"), 1.0, artwork_conflict=True)
    plan = SyncPlan(matches=[clean, fuzzy, conflict])

    report = build_health_report(scan("a"), scan("b"), plan)

    assert report.plan.unresolved_fuzzy_matches == 1
    assert report.plan.unresolved_conflicts == 1


def test_health_counts_unsupported_audio_like_extensions_from_scan_inventory(tmp_path: Path):
    (tmp_path / "album.aiff").write_bytes(b"not scanned as a supported format")
    (tmp_path / "notes.txt").write_text("not an audio format", encoding="utf-8")
    scan_a = scan_library(tmp_path, "a")
    report = build_health_report(scan_a, ScanResult(side="b", root=tmp_path / "empty"))

    assert report.library_a.unsupported_audio_files == 1
    assert report.library_b.unsupported_audio_files == 0


def test_health_report_marks_scan_errors_as_incomplete():
    report = build_health_report(scan("a", errors=["Could not read unreadable.mp3"]), scan("b"))

    assert report.library_a.health_check_complete is False
    assert report.library_a.health_check_errors == ("Could not read unreadable.mp3",)
    assert report.library_b.health_check_complete is True
