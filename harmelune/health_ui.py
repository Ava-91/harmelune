from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .health import HealthReport
from .ui_theme import configure_theme


class HealthDashboard(tk.Toplevel):
    """Read-only comparison of scan-derived library quality metrics."""

    def __init__(self, parent: tk.Misc, report: HealthReport) -> None:
        super().__init__(parent)
        self.title("Music Library Health")
        self.geometry("820x560")
        self.minsize(560, 400)
        self.transient(parent)
        configure_theme(self, dialog=True)
        self.report = report
        self._build()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-w>", lambda _event: self.destroy())

    def _build(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Library health", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="Read-only metrics from the latest scan. No files are changed.", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))
        columns = ("metric", "library_a", "library_b")
        table = ttk.Frame(root)
        table.pack(fill="both", expand=True)
        tree = ttk.Treeview(table, columns=columns, show="headings", height=12)
        for col, title, width in (("metric", "Metric", 330), ("library_a", "Library A", 180), ("library_b", "Library B", 180)):
            tree.heading(col, text=title)
            tree.column(col, width=width, minwidth=100, anchor="w")
        yscroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        a, b, plan = self.report.library_a, self.report.library_b, self.report.plan
        a_metadata = f"{a.complete_metadata} ({a.metadata_completeness_pct:.1f}%)" if a.track_count else "0 (N/A — empty)"
        b_metadata = f"{b.complete_metadata} ({b.metadata_completeness_pct:.1f}%)" if b.track_count else "0 (N/A — empty)"
        a_artwork = f"{a.artwork_tracks} ({a.artwork_coverage_pct:.1f}%)" if a.track_count else "0 (N/A — empty)"
        b_artwork = f"{b.artwork_tracks} ({b.artwork_coverage_pct:.1f}%)" if b.track_count else "0 (N/A — empty)"
        rows = (
            ("Health check completeness", "Complete" if a.health_check_complete else "INCOMPLETE", "Complete" if b.health_check_complete else "INCOMPLETE"),
            ("Tracks scanned", a.track_count, b.track_count),
            ("Unreadable / scan errors", a.unreadable_files, b.unreadable_files),
            ("Complete title + artist + album", a_metadata, b_metadata),
            ("Incomplete metadata tracks", a.incomplete_metadata_tracks, b.incomplete_metadata_tracks),
            ("Tracks with embedded artwork", a_artwork, b_artwork),
            ("Tracks missing embedded artwork", a.missing_artwork_tracks, b.missing_artwork_tracks),
            ("Unsupported audio-like formats", a.unsupported_audio_files, b.unsupported_audio_files),
            ("Duplicate groups (same file hash)", len(a.duplicate_groups), len(b.duplicate_groups)),
            ("Tracks participating in duplicate groups", a.duplicate_tracks, b.duplicate_tracks),
        )
        for row in rows:
            tree.insert("", "end", values=row)
        ttk.Separator(root).pack(fill="x", pady=12)
        ttk.Label(root, text=f"Plan review: {plan.unresolved_fuzzy_matches} uncertain match(es) · {plan.unresolved_conflicts} conflict(s)", style="Section.TLabel").pack(anchor="w")
        ttk.Label(root, text="Duplicate detection uses exact file hashes; different encodings of the same song may not be grouped. Unsupported-format counts cover common audio-like extensions that this scanner does not process.", style="Muted.TLabel", wraplength=760).pack(anchor="w", pady=(6, 6))
        errors = [("Library A", a.health_check_errors), ("Library B", b.health_check_errors)]
        visible_errors = [f"{name}: {message}" for name, items in errors for message in items[:3]]
        if visible_errors:
            ttk.Label(root, text="Health results may be incomplete: " + " · ".join(visible_errors), style="Muted.TLabel", wraplength=760).pack(anchor="w", pady=(0, 8))
        ttk.Button(root, text="Close", command=self.destroy, style="Primary.TButton").pack(anchor="e")


def open_health_dashboard(parent: tk.Misc, report: HealthReport) -> None:
    dialog = HealthDashboard(parent, report)
    parent.wait_window(dialog)
