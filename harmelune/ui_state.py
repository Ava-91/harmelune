from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=tuple[str, ...])

CATEGORIES = ("exact", "a_only", "b_only", "fuzzy", "conflicts")


def comparison_counts(rows: Iterable[tuple[str, object, object, object]]) -> dict[str, int]:
    """Count comparison rows by their stable category key."""
    counts = {category: 0 for category in CATEGORIES}
    for row in rows:
        category = row[0]
        if category in counts:
            counts[category] += 1
    return counts


def filter_comparison_rows(
    rows: Sequence[tuple[str, object, object, object]], category: str = "all"
) -> list[tuple[str, object, object, object]]:
    """Return all rows or rows belonging to a known category."""
    if category == "all":
        return list(rows)
    if category not in CATEGORIES:
        raise ValueError(f"Unknown comparison category: {category}")
    return [row for row in rows if row[0] == category]


def workflow_step(
    library_a_selected: bool,
    library_b_selected: bool,
    plan,
    preview_ready: bool,
    review_choices: dict | None = None,
) -> str:
    """Describe the next primary UI step without performing filesystem work."""
    if not library_a_selected or not library_b_selected:
        return "01  Select libraries"
    if plan is None:
        return "02  Compare"
    fuzzy = any(not match.confirmed for match in plan.matches)
    conflict_count = sum(match.metadata_conflict or match.artwork_conflict for match in plan.matches)
    if fuzzy or (conflict_count and len(review_choices or {}) < conflict_count):
        return "03  Review"
    if not preview_ready:
        return "04  Preview"
    return "05  Back up & apply"
