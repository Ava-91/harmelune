"""Windows-only integration tests for the native Tk comparison workspace.

These tests create the real Tkinter application and exercise the actual widgets
and callbacks with synthetic comparison rows. They never scan or modify music
files.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

if sys.platform != "win32":
    pytest.skip("Native Tk integration runs on the Windows GUI runner", allow_module_level=True)

import app as app_module


ROWS = [
    ("b_only", "Only in Library B", "1", "Zebra — Song · B:/Music/zebra.flac"),
    ("fuzzy", "Uncertain match", "1", "Moon — Song · A:/Music/moon.flac"),
    ("a_only", "Only in Library A", "1", "alpha — Song · A:/Music/alpha.flac"),
]


class _SettingsStore:
    def load(self):
        return app_module.Settings()


class _Journal:
    def __init__(self, *_args, **_kwargs):
        pass

    def unfinished(self):
        return []


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


@pytest.fixture
def gui(monkeypatch):
    """Build the actual application without first-run dialogs or user config."""
    monkeypatch.setattr(app_module, "SettingsStore", _SettingsStore)
    monkeypatch.setattr(app_module, "is_first_run", lambda _settings: False)
    monkeypatch.setattr(app_module, "OperationJournal", _Journal)

    window = app_module.HarmeluneApp()
    window.plan = SimpleNamespace(matches=[])
    window._comparison_rows = lambda: list(ROWS)
    # Health summaries depend on completed scans; keep this integration focused
    # on the real filter widgets and real result-table renderer.
    window._refresh_health = lambda: window._refresh_result_table()
    window._refresh_result_table()
    window.update_idletasks()
    window.update()
    yield window
    try:
        window.destroy()
    except Exception:
        pass


def _visible_details(window):
    return [
        str(window.tree.item(item, "values")[2])
        for item in window.tree.get_children("")
    ]


def test_search_entry_filters_real_tree_and_escape_clears_it(gui):
    entries = [w for w in _walk_widgets(gui) if isinstance(w, app_module.ttk.Entry)]
    search = next(
        w for w in entries
        if str(w.cget("textvariable")) == str(gui.comparison_query_var)
    )

    assert len(_visible_details(gui)) == len(ROWS)
    gui.comparison_query_var.set("MOON")
    gui.update()

    assert _visible_details(gui) == [ROWS[1][3]]
    assert "1 row(s)" in gui.result_summary_var.get()

    search.focus_set()
    gui.update()
    search.event_generate("<Escape>")
    gui.update()

    assert len(_visible_details(gui)) == len(ROWS)
    assert gui.comparison_query_var.get() == ""


def test_sort_combobox_reorders_real_tree(gui):
    combos = [w for w in _walk_widgets(gui) if isinstance(w, app_module.ttk.Combobox)]
    sort_combo = next(
        w for w in combos
        if str(w.cget("textvariable")) == str(gui.comparison_sort_var)
    )

    gui.comparison_sort_var.set("Details A–Z")
    sort_combo.event_generate("<<ComboboxSelected>>")
    gui.update()
    assert _visible_details(gui) == [ROWS[2][3], ROWS[1][3], ROWS[0][3]]

    gui.comparison_sort_var.set("Details Z–A")
    sort_combo.event_generate("<<ComboboxSelected>>")
    gui.update()
    assert _visible_details(gui) == [ROWS[0][3], ROWS[1][3], ROWS[2][3]]


def test_category_filter_and_clear_filters_button_work_together(gui):
    gui.summary_buttons["fuzzy"].invoke()
    gui.update()
    assert _visible_details(gui) == [ROWS[1][3]]
    assert gui.active_filter == "fuzzy"

    gui.comparison_query_var.set("not present")
    gui.update()
    assert _visible_details(gui) == []

    clear_button = next(
        w for w in _walk_widgets(gui)
        if isinstance(w, app_module.ttk.Button)
        and w.cget("text") == "Clear result filters"
    )
    clear_button.invoke()
    gui.update()

    assert gui.active_filter == "all"
    assert gui.comparison_query_var.get() == ""
    assert _visible_details(gui) == [row[3] for row in ROWS]
    assert "3 row(s)" in gui.result_summary_var.get()
