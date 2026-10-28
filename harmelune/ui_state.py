from __future__ import annotations

from collections.abc import Iterable, Sequence
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


def search_comparison_rows(
    rows: Sequence[tuple[str, object, object, object]], query: str = ""
) -> list[tuple[str, object, object, object]]:
    """Search comparison rows across category, label, count, and details."""
    needle = query.casefold().strip()
    if not needle:
        return list(rows)
    return [
        row for row in rows
        if needle in " ".join(str(value) for value in row).casefold()
    ]


def sort_comparison_rows(
    rows: Sequence[tuple[str, object, object, object]], sort_by: str = "Original order"
) -> list[tuple[str, object, object, object]]:
    """Sort comparison rows without mutating the original sequence."""
    if sort_by == "Original order":
        return list(rows)
    if sort_by == "Category":
        return sorted(rows, key=lambda row: (str(row[0]).casefold(), str(row[1]).casefold(), str(row[3]).casefold()))
    if sort_by == "Details A–Z":
        return sorted(rows, key=lambda row: str(row[3]).casefold())
    if sort_by == "Details Z–A":
        return sorted(rows, key=lambda row: str(row[3]).casefold(), reverse=True)
    raise ValueError(f"Unknown comparison sort: {sort_by}")


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
