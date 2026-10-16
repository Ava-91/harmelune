from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .display import display_path
from .models import ScanResult, SyncPlan
from .scanner import AUDIO_EXTENSIONS


@dataclass(frozen=True, slots=True)
class LibraryHealth:
    track_count: int
    unreadable_files: int
    complete_metadata: int
    metadata_completeness_pct: float
    artwork_tracks: int
    artwork_coverage_pct: float
    duplicate_groups: tuple[tuple[str, ...], ...] = ()
    duplicate_tracks: int = 0
    missing_artwork_tracks: int = 0
    incomplete_metadata_tracks: int = 0
    unsupported_audio_files: int = 0
    health_check_complete: bool = True
    health_check_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanHealth:
    unresolved_conflicts: int
    unresolved_fuzzy_matches: int


@dataclass(frozen=True, slots=True)
class HealthReport:
    library_a: LibraryHealth
    library_b: LibraryHealth
    plan: PlanHealth


def _library_health(scan: ScanResult) -> LibraryHealth:
    count = len(scan.tracks)
    complete = sum(bool(track.title and track.artist and track.album) for track in scan.tracks)
    artwork = sum(track.artwork_count > 0 for track in scan.tracks)
    missing_artwork = sum(track.artwork_count == 0 for track in scan.tracks)
    incomplete_metadata = count - complete
    unsupported_audio = scan.unsupported_audio_files
    check_errors = tuple(scan.errors)
    check_complete = scan.enumeration_complete and not scan.errors
    hashes: dict[str, list[str]] = defaultdict(list)
    for track in scan.tracks:
        if track.file_hash:
            hashes[track.file_hash].append(display_path(track.path))
    duplicate_groups = tuple(sorted(tuple(sorted(paths)) for paths in hashes.values() if len(paths) > 1))
    duplicate_tracks = sum(len(group) for group in duplicate_groups)
    return LibraryHealth(
        track_count=count,
        unreadable_files=len(scan.errors),
        complete_metadata=complete,
        metadata_completeness_pct=(complete * 100.0 / count) if count else 100.0,
        artwork_tracks=artwork,
        artwork_coverage_pct=(artwork * 100.0 / count) if count else 100.0,
        duplicate_groups=duplicate_groups,
        duplicate_tracks=duplicate_tracks,
        missing_artwork_tracks=missing_artwork,
        incomplete_metadata_tracks=incomplete_metadata,
        unsupported_audio_files=unsupported_audio,
        health_check_complete=check_complete,
        health_check_errors=check_errors,
    )


def build_health_report(scan_a: ScanResult, scan_b: ScanResult, plan: SyncPlan | None = None) -> HealthReport:
    """Compute read-only library quality statistics from the current scan/plan."""
    matches = plan.matches if plan else []
    return HealthReport(
        library_a=_library_health(scan_a),
        library_b=_library_health(scan_b),
        plan=PlanHealth(
            unresolved_conflicts=sum(match.metadata_conflict or match.artwork_conflict for match in matches),
            unresolved_fuzzy_matches=sum(not match.confirmed for match in matches),
        ),
    )
