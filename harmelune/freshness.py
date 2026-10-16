from __future__ import annotations

from .models import FileState, SyncPlan
from .scanner import current_fingerprint


class StalePlanError(RuntimeError):
    """Raised when a synchronization plan no longer describes the libraries."""


def _fingerprint_signature(fingerprint: dict[str, FileState]) -> dict[str, tuple[int, int, str | None]]:
    """Include content hashes: size and mtime alone are not a freshness guarantee."""
    return {
        path: (state.size, state.modified_ns, state.file_hash)
        for path, state in fingerprint.items()
    }


def validate_plan_freshness(plan: SyncPlan) -> None:
    """Block execution unless both libraries still match their scanned content fingerprints."""
    if not plan.library_a_root or not plan.library_b_root:
        raise StalePlanError("The synchronization plan has no library roots. Scan both libraries again.")
    if plan.fingerprint_a is None or plan.fingerprint_b is None:
        raise StalePlanError("The synchronization plan has no filesystem fingerprints. Scan both libraries again.")

    try:
        current_a = current_fingerprint(plan.library_a_root)
        current_b = current_fingerprint(plan.library_b_root)
    except (OSError, ValueError) as exc:
        raise StalePlanError(f"A library is unavailable or could not be fingerprinted. Scan both libraries again. ({exc})") from exc

    if _fingerprint_signature(plan.fingerprint_a) != _fingerprint_signature(current_a):
        raise StalePlanError("Library A content changed after scanning. Scan both libraries again before applying the plan.")
    if _fingerprint_signature(plan.fingerprint_b) != _fingerprint_signature(current_b):
        raise StalePlanError("Library B content changed after scanning. Scan both libraries again before applying the plan.")
