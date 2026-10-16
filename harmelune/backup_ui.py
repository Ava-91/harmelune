from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .backups import BackupInfo, list_backups, restore_backup
from .backup import MANIFEST_NAME, BackupVerificationError, verify_backup_contents
from .display import display_path
from .ui_theme import configure_theme


def _format_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


class BackupManagerDialog(tk.Toplevel):
    """Browse and safely restore Harmelune backups."""

    def __init__(self, parent: tk.Misc, target: Path, backup_root: Path) -> None:
        super().__init__(parent)
        self.title("Backup Manager")
        self.geometry("900x560")
        self.minsize(600, 420)
        self.transient(parent)
        configure_theme(self, dialog=True)
        self.grab_set()
        self.target = target
        self.backup_root = backup_root
        self.backups: list[BackupInfo] = []
        self.restored = False
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="💾 Backup Manager", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text=f"Backups: {display_path(self.backup_root)}", wraplength=700).pack(anchor="w", pady=(4, 12))
        columns = ("created", "files", "size", "verification", "path")
        table = ttk.Frame(root)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=15)
        for column, title, width in (("created", "Created", 145), ("files", "Files", 65), ("size", "Size", 85), ("verification", "Verification", 145), ("path", "Location", 360)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=65, anchor="w")
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Select a backup and verify it before restoring.")
        ttk.Label(root, textvariable=self.status, style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=(8, 0))
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(actions, text="Check integrity", command=self.verify_selected).pack(side="left", padx=8)
        ttk.Button(actions, text="Restore selected", command=self.restore, style="Danger.TButton").pack(side="right")
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right", padx=8)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Return>", lambda _event: self.verify_selected())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-w>", lambda _event: self.destroy())
        self.verification: dict[str, tuple[str, str]] = {}

    def refresh(self) -> None:
        self.backups = list_backups(self.backup_root)
        self.verification = {}
        for item in self.tree.get_children():
            self.tree.delete(item)
        for backup in self.backups:
            status = "Manifest · integrity-checkable" if (backup.path / MANIFEST_NAME).is_file() else "Legacy · unverified"
            self.tree.insert("", "end", iid=str(backup.path), values=(backup.created_at.strftime("%Y-%m-%d %H:%M:%S"), backup.file_count, _format_size(backup.size_bytes), status, display_path(backup.path)))
        self.status.set(f"{len(self.backups)} backup(s) found. Verify a snapshot before restoring it.")

    def _selected_backup(self) -> BackupInfo | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Select a backup", "Choose a backup first.", parent=self)
            return None
        selected_path = selection[0]
        return next((item for item in self.backups if str(item.path) == selected_path), None)

    def _selection_changed(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            self.status.set("Select a backup to inspect or verify it.")
            return
        selected_path = selection[0]
        result = self.verification.get(selected_path)
        self.status.set(result[1] if result else "Not verified yet. Use Verify selected before restoring.")

    def verify_selected(self) -> None:
        backup = self._selected_backup()
        if backup is None:
            return
        if not (backup.path / MANIFEST_NAME).is_file():
            message = "Legacy backup has no verification manifest. It cannot be cryptographically verified; restore requires explicit acknowledgement."
            self.verification[str(backup.path)] = ("legacy", message)
            self.status.set(message)
            self.tree.set(str(backup.path), "verification", "Legacy · unverified")
            return
        try:
            info = verify_backup_contents(backup.path)
        except (BackupVerificationError, OSError, ValueError) as exc:
            message = f"VERIFICATION FAILED: {exc}"
            self.verification[str(backup.path)] = ("failed", message)
            self.status.set(message)
            self.tree.set(str(backup.path), "verification", "FAILED")
            messagebox.showerror("Backup verification failed", message, parent=self)
            return
        message = f"Integrity check passed: {info.file_count} file(s), {_format_size(info.size_bytes)}. SHA-256 matches the stored manifest; this does not prove who created the backup or protect against a rewritten manifest."
        self.verification[str(backup.path)] = ("verified", message)
        self.status.set(message)
        self.tree.set(str(backup.path), "verification", "Integrity checked")
        messagebox.showinfo("Backup verified", message, parent=self)

    def restore(self) -> None:
        backup = self._selected_backup()
        if backup is None:
            return
        state = self.verification.get(str(backup.path))
        has_manifest = (backup.path / MANIFEST_NAME).is_file()
        if has_manifest and (state is None or state[0] != "verified"):
            messagebox.showwarning("Verify before restore", "This backup has a verification manifest. Verify it successfully before restoring.", parent=self)
            return
        if state is not None and state[0] == "failed":
            messagebox.showerror("Restore blocked", "This backup failed verification and will not be restored.", parent=self)
            return
        legacy_warning = "\n\nWARNING: This legacy backup has no verification manifest. Its contents cannot be verified against a trusted manifest." if not has_manifest else ""
        if not messagebox.askyesno(
            "Restore backup?",
            f"Restore this backup?\n\n{backup.path}\n\nThe current library will be backed up before restoration.{legacy_warning}",
            parent=self,
        ):
            return
        try:
            protection = restore_backup(backup.path, self.target, self.backup_root)
        except Exception as exc:
            messagebox.showerror("Restore failed", str(exc), parent=self)
            self.status.set(f"Restore failed: {exc}")
            return
        self.restored = True
        messagebox.showinfo("Restore complete", f"Backup restored.\n\nYour previous library was protected at:\n{protection}", parent=self)
        self.refresh()


def open_backup_manager(parent: tk.Misc, target: Path, backup_root: Path) -> BackupManagerDialog:
    dialog = BackupManagerDialog(parent, target, backup_root)
    parent.wait_window(dialog)
    return dialog
