from pathlib import Path


def test_app_has_no_developer_music_paths():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "E:\\Ava files" not in source
    assert "DEFAULT_LAPTOP" not in source
    assert "DEFAULT_PHONE_COPY" not in source
    assert "Ava Music Sync" not in source


def test_app_uses_generic_v1_components():
    source = Path("app.py").read_text(encoding="utf-8")
    for required in (
        "SettingsStore",
        "MasterLibrary",
        "SyncMode",
        "build_health_report",
        "execute_safe",
        "execute_reconcile",
        "execute_mirror",
        "dry_run_safe",
        "dry_run_reconcile",
        "dry_run_mirror",
        "report_from_safe",
        "report_from_reconcile",
        "report_from_mirror",
    ):
        assert required in source


def test_app_module_imports_without_constructing_a_window():
    import app

    assert hasattr(app, "HarmeluneApp")


def test_escape_during_scan_requests_cancellation_without_clearing_search():
    import app

    class SearchVar:
        def get(self):
            return "active query"

    class Window:
        scan_active = True
        comparison_query_var = SearchVar()
        cancellation_requested = False

        def cancel_scan(self):
            self.cancellation_requested = True

    window = Window()

    assert app.HarmeluneApp._clear_comparison_search(window) == "break"
    assert window.cancellation_requested
    assert window.comparison_query_var.get() == "active query"
