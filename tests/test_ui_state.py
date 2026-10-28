from types import SimpleNamespace

import pytest

from harmelune.ui_state import (
    comparison_counts,
    filter_comparison_rows,
    search_comparison_rows,
    sort_comparison_rows,
    workflow_step,
)


def test_comparison_counts_and_category_filters_are_data_driven():
    rows = [
        ("exact", "Exact", "1", "track A"),
        ("exact", "Exact", "1", "track B"),
        ("a_only", "Only A", "1", "track C"),
        ("fuzzy", "Fuzzy", "1", "track D"),
        ("conflicts", "Conflict", "1", "track E"),
    ]

    assert comparison_counts(rows) == {
        "exact": 2,
        "a_only": 1,
        "b_only": 0,
        "fuzzy": 1,
        "conflicts": 1,
    }
    assert [row[3] for row in filter_comparison_rows(rows, "fuzzy")] == ["track D"]
    assert filter_comparison_rows(rows, "all") == rows


def test_unknown_comparison_filter_is_rejected():
    with pytest.raises(ValueError, match="Unknown comparison category"):
        filter_comparison_rows([], "not-a-category")


def test_workflow_requires_both_libraries_then_comparison():
    assert workflow_step(False, True, None, False) == "01  Select libraries"
    assert workflow_step(True, True, None, False) == "02  Compare"


def test_workflow_requires_fuzzy_review_before_preview():
    plan = SimpleNamespace(matches=[SimpleNamespace(confirmed=False, metadata_conflict=False, artwork_conflict=False)])
    assert workflow_step(True, True, plan, False, {}) == "03  Review"


def test_workflow_requires_conflict_review_and_then_preview():
    plan = SimpleNamespace(matches=[SimpleNamespace(confirmed=True, metadata_conflict=True, artwork_conflict=False)])
    assert workflow_step(True, True, plan, False, {}) == "03  Review"
    assert workflow_step(True, True, plan, False, {"track": "keep-a"}) == "04  Preview"
    assert workflow_step(True, True, plan, True, {"track": "keep-a"}) == "05  Back up & apply"


def test_workflow_does_not_block_safe_preview_when_there_are_no_review_items():
    plan = SimpleNamespace(matches=[SimpleNamespace(confirmed=True, metadata_conflict=False, artwork_conflict=False)])
    assert workflow_step(True, True, plan, False, {}) == "04  Preview"
    assert workflow_step(True, True, plan, True, {}) == "05  Back up & apply"


def test_search_matches_category_label_and_details_case_insensitively():
    rows = [
        ("fuzzy", "Uncertain match", "1", "Artist — Moon Song · C:/Music/moon.flac"),
        ("conflicts", "Conflict", "1", "Artist — Rain Song · B:/Music/rain.flac"),
    ]

    assert search_comparison_rows(rows, "  MOON ") == [rows[0]]
    assert search_comparison_rows(rows, "conflict") == [rows[1]]
    assert search_comparison_rows(rows, "") == rows
    assert search_comparison_rows(rows, "missing") == []


def test_sorting_is_case_insensitive_and_does_not_mutate_input():
    rows = [
        ("b_only", "Only in Library B", "1", "Zebra — Song"),
        ("a_only", "Only in Library A", "1", "alpha — Song"),
        ("exact", "Exact match", "1", "Moon — Song"),
    ]
    original = list(rows)

    assert [row[3] for row in sort_comparison_rows(rows, "Details A–Z")] == [
        "alpha — Song", "Moon — Song", "Zebra — Song"
    ]
    assert [row[3] for row in sort_comparison_rows(rows, "Details Z–A")] == [
        "Zebra — Song", "Moon — Song", "alpha — Song"
    ]
    assert sort_comparison_rows(rows, "Category")[0][0] == "a_only"
    assert sort_comparison_rows(rows, "Original order") == rows
    assert rows == original


def test_unknown_comparison_sort_is_rejected():
    with pytest.raises(ValueError, match="Unknown comparison sort"):
        sort_comparison_rows([], "random")
