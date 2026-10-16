from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from .models import SyncMode
from .path_safety import validate_backup_root, validate_library_pair
from .settings import Settings
from .ui_theme import configure_theme


@dataclass(slots=True)
class FirstRunState:
    library_a: str = ""
    library_b: str = ""
    master: str = "library_a"
    sync_mode: str = SyncMode.SAFE
    backup_location: str = ""

    def validate(self) -> None:
        if not self.library_a.strip() or not self.library_b.strip():
            raise ValueError("Select both Library A and Library B.")
        libraries = validate_library_pair(self.library_a.strip(), self.library_b.strip())
        if not self.backup_location.strip():
            raise ValueError("Select a backup location.")
        validate_backup_root(self.backup_location.strip(), libraries)
        if self.sync_mode not in {SyncMode.SAFE, SyncMode.RECONCILE, SyncMode.MIRROR}:
            raise ValueError("Select a valid sync mode.")
        if self.master not in {"library_a", "library_b"}:
            raise ValueError("Select a valid master library.")

    def to_settings(self, existing: Settings) -> Settings:
        self.validate()
        return Settings(
            library_a=self.library_a.strip(),
            library_b=self.library_b.strip(),
            master=self.master,
            sync_mode=self.sync_mode,
            backup_location=self.backup_location.strip(),
            fuzzy_threshold=existing.fuzzy_threshold,
            conflict_defaults=dict(existing.conflict_defaults),
            appearance=existing.appearance,
        )


def is_first_run(settings: Settings) -> bool:
    return not settings.library_a.strip() or not settings.library_b.strip()


class FirstRunWizard(tk.Toplevel):
    def __init__(self, parent: tk.Misc, initial: Settings) -> None:
        super().__init__(parent)
        self.title("Harmelune setup")
        self.geometry("700x520")
        self.minsize(560, 400)
        self.transient(parent)
        configure_theme(self, dialog=True)
        self.grab_set()
        self.state = FirstRunState(
            library_a=initial.library_a,
            library_b=initial.library_b,
            master=initial.master or "library_a",
            sync_mode=initial.sync_mode,
            backup_location=initial.backup_location,
        )
        self.initial_settings = initial
        self.result: Settings | None = None
        self.step = 0
        self._build()
        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<Control-w>", lambda _event: self.cancel())
        self._show_step()

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    def _build(self) -> None:
        root = ttk.Frame(self, padding=24)
        root.pack(fill="both", expand=True)
        self.title_label = ttk.Label(root, font=("Segoe UI", 16, "bold"))
        self.title_label.pack(anchor="w")
        self.description = ttk.Label(root, wraplength=640, justify="left")
        self.description.pack(anchor="w", pady=(8, 18))
        self.content = ttk.Frame(root)
        self.content.pack(fill="both", expand=True)
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(18, 0))
        self.back_button = ttk.Button(actions, text="Back", command=self.back)
        self.back_button.pack(side="left")
        ttk.Button(actions, text="Skip setup", command=self.skip).pack(side="left", padx=8)
        self.next_button = ttk.Button(actions, text="Next", command=self.next)
        self.next_button.pack(side="right")

    def _clear(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _path_field(self, label: str, attribute: str, title: str) -> None:
        row = ttk.Frame(self.content)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text=label, width=20).pack(side="left")
        value = tk.StringVar(value=getattr(self.state, attribute))
        value.trace_add("write", lambda *_args: setattr(self.state, attribute, value.get()))
        entry = ttk.Entry(row, textvariable=value)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.focus_set()
        ttk.Button(row, text="Browse", command=lambda: self._choose(value, attribute, title)).pack(side="left")

    def _choose(self, variable: tk.StringVar, attribute: str, title: str) -> None:
        path = filedialog.askdirectory(parent=self, title=title)
        if path:
            variable.set(path)
            setattr(self.state, attribute, path)

    def _show_step(self) -> None:
        self._clear()
        steps = [
            ("Welcome to Harmelune", "Set up two independent music libraries. Nothing is scanned, copied, deleted, or backed up by this wizard."),
            ("1. Select Library A", "Choose the first music folder. It can be anywhere on this Windows machine or an accessible drive."),
            ("2. Select Library B", "Choose a different music folder. Identical or nested libraries are rejected for safety."),
            ("3. Choose the master", "The master is the authoritative library when a directed operation needs one. There is no hidden laptop/phone preference."),
            ("4. Choose a sync mode", "Safe only adds missing files. Reconcile requires explicit decisions. Mirror is destructive and requires exact confirmation later."),
            ("5. Choose a backup location", "Backups are verified before modifying operations and cannot overlap either library."),
            ("Ready", "Next: Scan → Review → Dry run → Backup → Apply → Report. The wizard itself has not modified your music."),
        ]
        title, description = steps[self.step]
        self.title_label.configure(text=title)
        self.description.configure(text=description)
        if self.step == 1:
            self._path_field("Library A", "library_a", "Select Library A")
        elif self.step == 2:
            self._path_field("Library B", "library_b", "Select Library B")
        elif self.step == 3:
            self.master_var = tk.StringVar(value=self.state.master)
            for label, value in (("Library A", "library_a"), ("Library B", "library_b")):
                ttk.Radiobutton(self.content, text=label, variable=self.master_var, value=value).pack(anchor="w", pady=8)
        elif self.step == 4:
            self.mode_var = tk.StringVar(value=self.state.sync_mode)
            for label, value in (("Safe", SyncMode.SAFE), ("Reconcile", SyncMode.RECONCILE), ("Mirror", SyncMode.MIRROR)):
                ttk.Radiobutton(self.content, text=label, variable=self.mode_var, value=value).pack(anchor="w", pady=8)
        elif self.step == 5:
            self._path_field("Backup location", "backup_location", "Select backup location")
        elif self.step == 6:
            ttk.Label(self.content, text="Your music has not been changed. Click Finish to return to the main window and start a scan.", wraplength=620).pack(anchor="w", pady=20)
        self.back_button.configure(state="normal" if self.step else "disabled")
        self.next_button.configure(text="Finish" if self.step == len(steps) - 1 else "Next")

    def next(self) -> None:
        if self.step == 3:
            self.state.master = self.master_var.get()
        elif self.step == 4:
            self.state.sync_mode = self.mode_var.get()
        if self.step in {1, 2, 5}:
            value = self.state.library_a if self.step == 1 else self.state.library_b if self.step == 2 else self.state.backup_location
            if not value.strip():
                messagebox.showwarning("Setup incomplete", "Choose the requested folder before continuing.", parent=self)
                return
        if self.step == 2:
            try:
                validate_library_pair(self.state.library_a, self.state.library_b)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Unsafe library pair", str(exc), parent=self)
                return
        if self.step == 5:
            try:
                self.state.validate()
            except (OSError, ValueError) as exc:
                messagebox.showerror("Setup incomplete", str(exc), parent=self)
                return
        if self.step == 6:
            try:
                self.result = self.state.to_settings(self.initial_settings)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Setup incomplete", str(exc), parent=self)
                return
            self.destroy()
            return
        self.step += 1
        self._show_step()

    def back(self) -> None:
        if self.step:
            if self.step == 3:
                self.state.master = self.master_var.get()
            elif self.step == 4:
                self.state.sync_mode = self.mode_var.get()
            self.step -= 1
            self._show_step()

    def skip(self) -> None:
        self.result = None
        self.destroy()
