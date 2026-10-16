"""UI-independent orchestration for Harmelune's scan/review/apply workflow.

The Tkinter frontend and the future desktop sidecar share this layer. Safety
validation, previews, backups, freshness checks, and transactions remain in the
existing engine modules; this module only coordinates them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .direction import SyncDirection
from .dry_run import DryRunResult, dry_run_mirror, dry_run_reconcile, dry_run_safe
from .execution_report import ExecutionReport, report_from_mirror, report_from_reconcile, report_from_safe
from .matcher import build_plan
from .mirror import execute_mirror
from .models import ScanResult, SyncMode, SyncPlan
from .path_safety import validate_library_pair
from .reconcile import ReconcileDecision, execute_reconcile
from .scanner import scan_library
from .sync import execute_safe


ProgressCallback = Callable[[str, int], None]
CancelCallback = Callable[[], bool]


@dataclass(slots=True)
class ScanBundle:
    """Complete result of a two-library scan and comparison."""

    library_a: Path
    library_b: Path
    scan_a: ScanResult
    scan_b: ScanResult
    plan: SyncPlan


def scan_libraries(
    library_a: str | Path,
    library_b: str | Path,
    *,
    fuzzy_threshold: float = 0.88,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
    use_cache: bool = True,
) -> ScanBundle | None:
    """Scan and compare two libraries without modifying their contents.

    Returns None when cancellation is requested between/within scans. Progress
    callbacks receive ("a" or "b", files_visited). UI adapters must marshal
    progress updates to their UI thread.
    """
    root_a, root_b = validate_library_pair(library_a, library_b)
    is_cancelled = cancel or (lambda: False)

    def report(side: str) -> Callable[[int], None] | None:
        if progress is None:
            return None
        return lambda count: progress(side, count)

    result_a = scan_library(
        root_a, "a", progress=report("a"), cancel=is_cancelled, use_cache=use_cache
    )
    if is_cancelled() or any(error == "Scan cancelled by user" for error in result_a.errors):
        return None

    result_b = scan_library(
        root_b, "b", progress=report("b"), cancel=is_cancelled, use_cache=use_cache
    )
    if is_cancelled() or any(error == "Scan cancelled by user" for error in result_b.errors):
        return None

    plan = build_plan(result_a, result_b, threshold=fuzzy_threshold)
    return ScanBundle(root_a, root_b, result_a, result_b, plan)


def preview_workflow(
    plan: SyncPlan,
    mode: str,
    direction: SyncDirection,
    *,
    decisions: dict[str, ReconcileDecision] | None = None,
    backup_root: str | Path | None = None,
) -> DryRunResult:
    """Build a read-only preview for one supported mode.

    The underlying engine performs path validation and stale-plan checks. A
    Reconcile preview is refused until the caller supplies explicit decisions.
    """
    if mode == SyncMode.SAFE:
        return dry_run_safe(plan, direction)
    if mode == SyncMode.RECONCILE:
        if decisions is None:
            raise ValueError("Every Reconcile item needs an explicit decision.")
        if backup_root is None or not str(backup_root).strip():
            raise ValueError("A separate backup location is required for Reconcile preview.")
        return dry_run_reconcile(plan, decisions, Path(backup_root))
    if mode == SyncMode.MIRROR:
        return dry_run_mirror(plan, direction)
    raise ValueError(f"Unsupported sync mode: {mode!r}")


def execute_workflow(
    plan: SyncPlan,
    mode: str,
    direction: SyncDirection,
    backup_root: str | Path,
    *,
    decisions: dict[str, ReconcileDecision] | None = None,
    confirmation: str | None = None,
) -> ExecutionReport:
    """Execute a reviewed workflow through the existing safety-critical engine.

    This is intentionally not a bypass around UI review: callers must obtain
    user approval before calling it. The engine still revalidates paths and
    freshness, and creates/verifies backups before filesystem changes.
    """
    backup = Path(backup_root)
    if mode == SyncMode.SAFE:
        return report_from_safe(execute_safe(plan, direction, backup))
    if mode == SyncMode.RECONCILE:
        if decisions is None:
            raise ValueError("Every Reconcile item needs an explicit decision.")
        return report_from_reconcile(execute_reconcile(plan, decisions, backup))
    if mode == SyncMode.MIRROR:
        return report_from_mirror(execute_mirror(plan, direction, backup, confirmation or ""))
    raise ValueError(f"Unsupported sync mode: {mode!r}")
