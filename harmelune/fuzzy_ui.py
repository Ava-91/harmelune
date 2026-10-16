from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .ui_theme import configure_theme

from .explain import explain_match
from .models import Match, SyncPlan


class FuzzyReviewDialog(tk.Toplevel):
    """Ask the user to confirm or reject every uncertain track match."""

    def __init__(self, parent: tk.Misc, matches: list[Match]) -> None:
        super().__init__(parent)
        self.title("Review fuzzy matches")
        self.geometry("1040x690")
        self.minsize(640, 440)
        self.transient(parent)
        configure_theme(self, dialog=True)
        self.grab_set()
        self.matches = matches
        self.index = 0
        self.decisions: dict[str, bool] = {}
        self.result: dict[str, bool] | None = None
        self._build()
        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Control-w>", lambda _event: self.cancel())
        self._show_current()

    def _build(self) -> None:
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)
        self.counter = ttk.Label(root, font=("Segoe UI", 12, "bold"))
        self.counter.pack(anchor="w")
        self.explanation = ttk.Label(root, justify="left", wraplength=850)
        self.explanation.pack(anchor="w", pady=(8, 14))

        columns = ttk.Frame(root)
        columns.pack(fill="both", expand=True)
        self.panel_a = self._panel(columns, "Library A candidate")
        self.panel_a.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.panel_b = self._panel(columns, "Library B candidate")
        self.panel_b.pack(side="left", fill="both", expand=True, padx=(8, 0))

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=18)
        ttk.Button(actions, text="← Previous", command=self.previous).pack(side="left")
        ttk.Button(actions, text="✓ Confirm match", command=lambda: self.choose(True)).pack(side="left", padx=8)
        ttk.Button(actions, text="✕ Keep separate", command=lambda: self.choose(False)).pack(side="left")
        ttk.Button(actions, text="Finish Review", command=self.finish).pack(side="right")
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="right", padx=8)

    def _panel(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        return ttk.LabelFrame(parent, text=title, padding=14)

    def _populate(self, panel: ttk.Frame, track) -> None:
        for child in panel.winfo_children():
            child.destroy()
        ttk.Label(panel, text=track.display_title, font=("Segoe UI", 14, "bold"), wraplength=370).pack(anchor="w")
        ttk.Label(panel, text=f"Artist: {track.display_artist}").pack(anchor="w", pady=(12, 0))
        ttk.Label(panel, text=f"Album: {track.display_album}").pack(anchor="w")
        duration = f"{track.duration:.1f}s" if track.duration is not None else "Unknown"
        ttk.Label(panel, text=f"Duration: {duration}").pack(anchor="w")
        ttk.Label(panel, text=f"Format / size: {track.path.suffix.lower() or 'Unknown'} · {track.size:,} bytes").pack(anchor="w")
        ttk.Label(panel, text=f"Filename: {track.path.name}", wraplength=370).pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text=f"SHA-256: {track.file_hash or 'Unavailable'}", wraplength=370).pack(anchor="w")
        ttk.Label(panel, text=f"Artwork: {track.artwork_count} embedded image(s)").pack(anchor="w")

    def _show_current(self) -> None:
        if not self.matches:
            self.finish()
            return
        match = self.matches[self.index]
        details = explain_match(match)
        self.counter.configure(text=f"Fuzzy match {self.index + 1} of {len(self.matches)} — confidence {match.confidence:.0%}")
        reason_text = "Evidence: " + " • ".join(details.reasons)
        if details.conflicts:
            reason_text += "\nConflicts: " + " • ".join(details.conflicts)
        left_duration, right_duration = match.library_a.duration, match.library_b.duration
        if left_duration is not None and right_duration is not None:
            reason_text += f"\nDuration difference: {abs(left_duration - right_duration):.2f}s"
        else:
            reason_text += "\nDuration difference: unavailable (one or both files have no duration metadata)"
        self.explanation.configure(text=reason_text)
        self._populate(self.panel_a, match.library_a)
        self._populate(self.panel_b, match.library_b)

    def choose(self, same: bool) -> None:
        match = self.matches[self.index]
        self.decisions[str(match.library_a.path)] = same
        if self.index < len(self.matches) - 1:
            self.index += 1
            self._show_current()
        else:
            self.finish()

    def previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._show_current()

    def finish(self) -> None:
        self.result = dict(self.decisions)
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()


def review_fuzzy_matches(parent: tk.Misc, matches: list[Match]) -> dict[str, bool] | None:
    dialog = FuzzyReviewDialog(parent, matches)
    parent.wait_window(dialog)
    return dialog.result


def apply_fuzzy_decisions(plan: SyncPlan, decisions: dict[str, bool]) -> SyncPlan:
    """Apply explicit fuzzy decisions while preserving unresolved matches and plan metadata.

    Rejecting a fuzzy match means the two tracks are different songs. Both must remain
    independently represented so Mirror cannot treat the surviving side as deleteable.
    """
    remaining_matches: list[Match] = []
    library_a_only = list(plan.library_a_only)
    library_b_only = list(plan.library_b_only)
    for match in plan.matches:
        if match.confirmed:
            remaining_matches.append(match)
            continue
        decision = decisions.get(str(match.library_a.path))
        if decision is True:
            match.confirmed = True
            remaining_matches.append(match)
        elif decision is False:
            library_a_only.append(match.library_a)
            library_b_only.append(match.library_b)
        else:
            remaining_matches.append(match)

    return SyncPlan(
        library_a_only=library_a_only,
        library_b_only=library_b_only,
        matches=remaining_matches,
        library_a_root=plan.library_a_root,
        library_b_root=plan.library_b_root,
        fingerprint_a=plan.fingerprint_a,
        fingerprint_b=plan.fingerprint_b,
    )
