from __future__ import annotations
from .ui_theme import configure_theme

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .artwork import make_preview
from .explain import explain_match
from .models import Match
from .review import ConflictChoice, conflict_matches


class ConflictReviewDialog(tk.Toplevel):
    """Review metadata/artwork conflicts without changing files."""

    def __init__(self, parent: tk.Misc, matches: list[Match]) -> None:
        super().__init__(parent)
        self.title("Review conflicts")
        self.geometry("980x720")
        self.transient(parent)
        configure_theme(self, dialog=True)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-w>", lambda _event: self.destroy())
        self.matches = conflict_matches(matches)
        self.index = 0
        self.choices: dict[str, ConflictChoice] = {}
        self.result: dict[str, ConflictChoice] | None = None
        self._images: list[object] = []
        self._build()
        self._show_current()

    def _build(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        self.counter = ttk.Label(root, font=("Segoe UI", 11, "bold"))
        self.counter.pack(anchor="w")
        self.kind = ttk.Label(root)
        self.kind.pack(anchor="w", pady=(4, 6))
        self.evidence = ttk.Label(root, justify="left", wraplength=930)
        self.evidence.pack(anchor="w", pady=(0, 14))

        columns = ttk.Frame(root)
        columns.pack(fill="both", expand=True)
        self.left = self._track_panel(columns, "Library A")
        self.left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.right = self._track_panel(columns, "Library B")
        self.right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        choices = ttk.LabelFrame(root, text="Resolution", padding=12)
        choices.pack(fill="x", pady=18)
        self.choice = tk.StringVar(value=ConflictChoice.LAPTOP.value)
        for value, text in (("laptop", "Keep Library A"), ("phone", "Keep Library B"), ("skip", "Skip")):
            ttk.Radiobutton(choices, text=text, variable=self.choice, value=value).pack(side="left", padx=10)

        nav = ttk.Frame(root)
        nav.pack(fill="x")
        ttk.Button(nav, text="← Previous", command=self.previous).pack(side="left")
        ttk.Button(nav, text="Next →", command=self.next).pack(side="left", padx=8)
        ttk.Button(nav, text="Apply Review", command=self.finish).pack(side="right")
        ttk.Button(nav, text="Cancel", command=self.cancel).pack(side="right", padx=8)

    def _track_panel(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        return ttk.LabelFrame(parent, text=title, padding=12)

    def _clear_panel(self, panel: ttk.Frame) -> None:
        for child in panel.winfo_children():
            child.destroy()

    def _show_current(self) -> None:
        if not self.matches:
            self.finish()
            return
        match = self.matches[self.index]
        details = explain_match(match)
        self.counter.configure(text=f"Conflict {self.index + 1} of {len(self.matches)}")
        kinds = []
        if match.metadata_conflict:
            kinds.append("metadata")
        if match.artwork_conflict:
            kinds.append("artwork")
        self.kind.configure(text=" + ".join(kinds).title() + " conflict")
        evidence = "Evidence: " + " • ".join(details.reasons)
        if details.conflicts:
            evidence += "\nDetected: " + " • ".join(details.conflicts)
        self.evidence.configure(text=evidence)
        self._populate_track(self.left, match.library_a)
        self._populate_track(self.right, match.library_b)
        self.choice.set(self.choices.get(str(match.library_a.path), ConflictChoice.LAPTOP).value)

    def _populate_track(self, panel: ttk.Frame, track) -> None:
        self._clear_panel(panel)
        ttk.Label(panel, text=track.display_title, font=("Segoe UI", 12, "bold"), wraplength=380).pack(anchor="w")
        ttk.Label(panel, text=f"Artist: {track.display_artist}").pack(anchor="w", pady=(6, 0))
        ttk.Label(panel, text=f"Album: {track.display_album}").pack(anchor="w")
        duration = f"{track.duration:.1f}s" if track.duration is not None else "Unknown"
        ttk.Label(panel, text=f"Duration: {duration}").pack(anchor="w")
        ttk.Label(panel, text=f"File: {Path(track.path).name}", wraplength=380).pack(anchor="w")
        ttk.Label(panel, text=f"SHA-256: {track.file_hash or 'Unavailable'}", wraplength=380).pack(anchor="w")
        ttk.Label(panel, text=f"Artwork: {track.artwork_count} embedded image(s)").pack(anchor="w", pady=(0, 8))
        preview = make_preview(Path(track.path))
        if preview:
            self._images.append(preview)
            ttk.Label(panel, image=preview).pack(anchor="center", pady=8)
        else:
            ttk.Label(panel, text="No embedded artwork").pack(anchor="center", pady=38)

    def _save_choice(self) -> None:
        if self.matches:
            self.choices[str(self.matches[self.index].library_a.path)] = ConflictChoice(self.choice.get())

    def next(self) -> None:
        self._save_choice()
        if self.index < len(self.matches) - 1:
            self.index += 1
            self._show_current()

    def previous(self) -> None:
        self._save_choice()
        if self.index > 0:
            self.index -= 1
            self._show_current()

    def finish(self) -> None:
        self._save_choice()
        self.result = dict(self.choices)
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()


def review_conflicts(parent: tk.Misc, matches: list[Match]) -> dict[str, ConflictChoice] | None:
    dialog = ConflictReviewDialog(parent, matches)
    parent.wait_window(dialog)
    return dialog.result
