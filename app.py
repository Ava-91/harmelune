from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from harmelune.backup_ui import open_backup_manager
from harmelune.direction import MasterLibrary, SyncDirection
from harmelune.dry_run import dry_run_mirror, dry_run_reconcile, dry_run_safe
from harmelune.execution_report import ExecutionReport, report_from_mirror, report_from_reconcile, report_from_safe
from harmelune.report_exports import export_report as export_report_file
from harmelune.first_run import FirstRunWizard, is_first_run
from harmelune.fuzzy_ui import apply_fuzzy_decisions, review_fuzzy_matches
from harmelune.health import build_health_report
from harmelune.matcher import build_plan
from harmelune.models import SyncMode, SyncPlan
from harmelune.operation_journal import JournalCorruptError, OperationJournal
from harmelune.playlist import inspect_playlist, suggest_replacements
from harmelune.mirror import build_mirror_preview, execute_mirror
from harmelune.path_safety import validate_backup_root, validate_library_pair
from harmelune.reconcile import ReconcileDecision, execute_reconcile
from harmelune.review import ConflictChoice
from harmelune.scanner import scan_library
from harmelune.settings import Settings, SettingsStore, default_config_dir
from harmelune.sync import execute_safe
from harmelune.ui_state import comparison_counts, filter_comparison_rows, workflow_step
from harmelune.health_ui import open_health_dashboard
from harmelune.ui_theme import configure_theme


class HarmeluneApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Harmelune")
        self.geometry("1180x820")
        self.minsize(940, 660)
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.plan: SyncPlan | None = None
        self.scan_a = None
        self.scan_b = None
        self.library_a_root: Path | None = None
        self.library_b_root: Path | None = None
        self.last_report: ExecutionReport | None = None
        self.review_choices: dict[str, ConflictChoice] = {}
        self.health = None
        self.active_filter = "all"
        self.preview_ready = False
        self.last_dry_run = None
        self.scan_errors = 0
        self.cancel_scan_event = threading.Event()
        self.scan_active = False
        self.busy_started_at: float | None = None
        self.busy_clock_after: str | None = None
        self.elapsed_var = tk.StringVar(value="")
        self.library_a_var = tk.StringVar(value=self.settings.library_a)
        self.library_b_var = tk.StringVar(value=self.settings.library_b)
        self.master_var = tk.StringVar(value=self.settings.master or "library_a")
        self.mode_var = tk.StringVar(value=self.settings.sync_mode)
        self.backup_var = tk.StringVar(value=self.settings.backup_location)
        self.status_var = tk.StringVar(value="Choose Library A and Library B to begin.")
        self.workflow_var = tk.StringVar(value="01  Select libraries")
        self.workflow_help_var = tk.StringVar(value="Choose two different, accessible music folders.")
        self._build_ui()
        self.library_a_var.trace_add("write", lambda *_: self._invalidate_scan())
        self.library_b_var.trace_add("write", lambda *_: self._invalidate_scan())
        self.master_var.trace_add("write", lambda *_: self._invalidate_preview())
        self.mode_var.trace_add("write", lambda *_: self._invalidate_preview())
        self.backup_var.trace_add("write", lambda *_: self._invalidate_preview())
        self._update_controls()
        if is_first_run(self.settings):
            self.after(100, self._run_first_run)
            self.after(250, self._check_recovery_journal)
        else:
            self.after(150, self._check_recovery_journal)

    def _check_recovery_journal(self) -> None:
        """Warn about interrupted operations; never resume filesystem changes automatically."""
        journal = OperationJournal(default_config_dir() / "operations.json")
        try:
            unfinished = journal.unfinished()
        except JournalCorruptError as exc:
            messagebox.showwarning(
                "Operation journal needs inspection",
                f"{exc}\n\nNo operation will be resumed automatically. Preserve the journal file and inspect it before syncing.",
                parent=self,
            )
            return
        if not unfinished:
            return
        details = []
        for record in unfinished[:5]:
            details.append(
                f"Operation {record.operation_id[:12]} · {record.mode}\n"
                f"Affected paths: {len(record.affected_paths)}\n"
                f"Backups: {', '.join(record.backup_paths) or 'not recorded'}"
            )
        if len(unfinished) > 5:
            details.append(f"... and {len(unfinished) - 5} more interrupted operation(s).")
        messagebox.showwarning(
            "Interrupted operation detected",
            "Harmelune found an operation without a recorded final state. "
            "It will NOT resume automatically. Inspect the affected library and verify the listed backup before starting another sync.\n\n"
            + "\n\n".join(details),
            parent=self,
        )

    def _run_first_run(self) -> None:
        wizard = FirstRunWizard(self, self.settings)
        self.wait_window(wizard)
        if wizard.result is None:
            self.status_var.set("Setup skipped — choose Library A and Library B when you are ready.")
            return
        try:
            self.settings_store.save(wizard.result)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Setup could not be saved", str(exc), parent=self)
            return
        self.settings = wizard.result
        self.library_a_var.set(self.settings.library_a)
        self.library_b_var.set(self.settings.library_b)
        self.master_var.set(self.settings.master)
        self.mode_var.set(self.settings.sync_mode)
        self.backup_var.set(self.settings.backup_location)
        self.status_var.set("Setup saved — ready to scan. Nothing has been changed in either library.")

    def _configure_theme(self) -> None:
        configure_theme(self)

    def _build_ui(self) -> None:
        self._configure_theme()
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="harmelune", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="YOUR MUSIC, IN HARMONY.  ·  LOCAL-FIRST LIBRARY CARE", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(frame, textvariable=self.workflow_var, style="Section.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(frame, textvariable=self.workflow_help_var, style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        paths = ttk.LabelFrame(frame, text="01  MUSIC LIBRARIES", padding=10)
        paths.pack(fill="x", pady=(0, 8))
        self._path_row(paths, "Library A", self.library_a_var)
        self._path_row(paths, "Library B", self.library_b_var)
        options = ttk.Frame(frame)
        options.pack(fill="x", pady=(2, 8))
        self._combo_row(options, "Master", self.master_var, ["library_a", "library_b"])
        self._combo_row(options, "Mode", self.mode_var, [SyncMode.SAFE, SyncMode.RECONCILE, SyncMode.MIRROR])
        self._path_row(options, "Backup location", self.backup_var, "Select backup folder")
        summary = ttk.LabelFrame(frame, text="02  COMPARISON SNAPSHOT  ·  SELECT A CATEGORY TO FILTER", padding=8)
        summary.pack(fill="x", pady=(0, 8))
        cards = ttk.Frame(summary)
        cards.pack(fill="x")
        self.summary_buttons = {}
        for key, label in (("exact", "Exact matches"), ("a_only", "Only in A"), ("b_only", "Only in B"), ("fuzzy", "Review fuzzy"), ("conflicts", "Conflicts")):
            button = ttk.Button(cards, text=f"{label}\n—", command=lambda category=key: self.filter_results(category))
            button.pack(side="left", fill="x", expand=True, padx=3)
            self.summary_buttons[key] = button
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(0, 8))
        self.scan_button = ttk.Button(actions, text="Compare libraries", command=self.scan, style="Primary.TButton")
        self.scan_button.pack(side="left")
        self.review_conflicts_button = ttk.Button(actions, text="Review conflicts", command=self.review_conflicts, state="disabled")
        self.review_conflicts_button.pack(side="left", padx=(7, 0))
        self.review_fuzzy_button = ttk.Button(actions, text="Review uncertain matches", command=self.review_fuzzy, state="disabled")
        self.review_fuzzy_button.pack(side="left", padx=(7, 0))
        self.dry_run_button = ttk.Button(actions, text="Preview plan", command=self.dry_run, style="Primary.TButton", state="disabled")
        self.dry_run_button.pack(side="left", padx=(7, 0))
        self.execute_button = ttk.Button(actions, text="Back up & apply…", command=self.execute, style="Danger.TButton", state="disabled")
        self.execute_button.pack(side="left", padx=(7, 0))
        advanced = ttk.LabelFrame(frame, text="ADVANCED TOOLS", padding=8)
        advanced.pack(fill="x", pady=(0, 8))
        self.export_button = ttk.Button(advanced, text="Export last report", command=self.export_report, state="disabled")
        self.export_button.pack(side="left")
        self.backups_a_button = ttk.Button(advanced, text="Backups A · Manage", command=lambda: self.open_backups(self.library_a_var), state="normal" if self.library_a_var.get().strip() else "disabled")
        self.backups_a_button.pack(side="left", padx=(7, 0))
        self.backups_b_button = ttk.Button(advanced, text="Backups B · Manage", command=lambda: self.open_backups(self.library_b_var), state="normal" if self.library_b_var.get().strip() else "disabled")
        self.backups_b_button.pack(side="left", padx=(7, 0))
        self.health_button = ttk.Button(advanced, text="Library health…", command=self.show_health, state="disabled")
        self.health_button.pack(side="left", padx=(7, 0))
        self.playlist_button = ttk.Button(advanced, text="Check playlist…", command=self.check_playlist)
        self.playlist_button.pack(side="left", padx=(7, 0))
        ttk.Button(advanced, text="Clear result filter", command=lambda: self.filter_results("all")).pack(side="right")
        results = ttk.LabelFrame(frame, text="03  RESULTS", padding=8)
        results.pack(fill="both", expand=True)
        result_table = ttk.Frame(results)
        result_table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(result_table, columns=("category", "count", "details"), show="headings", height=10, selectmode="browse")
        for column, title, width in (("category", "Category", 180), ("count", "Count", 70), ("details", "Details", 640)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=70, anchor="w")
        result_y = ttk.Scrollbar(result_table, orient="vertical", command=self.tree.yview)
        result_x = ttk.Scrollbar(result_table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=result_y.set, xscrollcommand=result_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        result_y.grid(row=0, column=1, sticky="ns")
        result_x.grid(row=1, column=0, sticky="ew")
        result_table.rowconfigure(0, weight=1)
        result_table.columnconfigure(0, weight=1)
        self.tree.bind("<Return>", lambda _event: self._show_selected_result_details())
        progress_row = ttk.Frame(frame)
        progress_row.pack(fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(progress_row, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(progress_row, textvariable=self.elapsed_var, style="Muted.TLabel", width=8, anchor="e").pack(side="left", padx=8)
        self.cancel_button = ttk.Button(progress_row, text="Cancel scan", command=self.cancel_scan, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Label(frame, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        self.bind("<F5>", lambda _event: self.scan())
        self.bind("<Control-p>", lambda _event: self.dry_run())
        self.bind("<Control-h>", lambda _event: self.show_health())
        self.bind("<Escape>", lambda _event: self.cancel_scan() if self.scan_active else None)

    def _show_selected_result_details(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        if len(values) >= 3:
            messagebox.showinfo(str(values[0]), str(values[2]), parent=self)

    def _path_row(self, parent: ttk.Frame, label: str, variable: tk.StringVar, browse_title: str = "Select music library") -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse", command=lambda: self.browse(variable, browse_title)).pack(side="left")

    def _combo_row(self, parent: ttk.Frame, label: str, variable: tk.StringVar, values: list[str]) -> None:
        row = ttk.Frame(parent)
        row.pack(side="left", padx=(0, 18))
        ttk.Label(row, text=label).pack(side="left", padx=(0, 6))
        combo = ttk.Combobox(row, textvariable=variable, values=values, state="readonly", width=14)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _event: (self._save_settings(), self._update_controls()))

    def browse(self, variable: tk.StringVar, title: str) -> None:
        path = filedialog.askdirectory(title=title)
        if path:
            variable.set(path)
            self._save_settings()
            self._update_backup_buttons()

    def _save_settings(self) -> None:
        settings = Settings(
            library_a=self.library_a_var.get().strip(), library_b=self.library_b_var.get().strip(),
            master=self.master_var.get().strip(), sync_mode=self.mode_var.get().strip(),
            backup_location=self.backup_var.get().strip(), fuzzy_threshold=self.settings.fuzzy_threshold,
            conflict_defaults=self.settings.conflict_defaults, appearance=self.settings.appearance,
        )
        self.settings_store.save(settings)
        self.settings = settings

    def _invalidate_preview(self) -> None:
        self.preview_ready = False
        self.last_dry_run = None
        if hasattr(self, "execute_button"):
            self._update_controls()

    def _invalidate_scan(self) -> None:
        self.plan = None
        self.scan_a = None
        self.scan_b = None
        self.library_a_root = None
        self.library_b_root = None
        self.last_report = None
        self.health = None
        self.review_choices = {}
        self.preview_ready = False
        self.last_dry_run = None
        self.active_filter = "all"
        if hasattr(self, "tree"):
            for item in self.tree.get_children():
                self.tree.delete(item)
        if hasattr(self, "summary_buttons"):
            for button in self.summary_buttons.values():
                button.configure(state="disabled")
        if hasattr(self, "execute_button"):
            self._update_controls()

    def _update_backup_buttons(self) -> None:
        self.backups_a_button.configure(state="normal" if self.library_a_var.get().strip() else "disabled")
        self.backups_b_button.configure(state="normal" if self.library_b_var.get().strip() else "disabled")

    def open_backups(self, variable: tk.StringVar) -> None:
        target_text = variable.get().strip()
        backup_text = self.backup_var.get().strip()
        if not target_text:
            messagebox.showwarning("Backup Manager", "Choose a library first.", parent=self)
            return
        if not backup_text:
            messagebox.showwarning("Backup Manager", "Choose a backup location first.", parent=self)
            return
        target = Path(target_text).expanduser()
        backup_root = Path(backup_text).expanduser()
        if not target.is_dir():
            messagebox.showerror("Backup Manager", f"Library does not exist or is not a directory:\n{target}", parent=self)
            return
        try:
            validate_backup_root(backup_root, (target,))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Backup Manager", str(exc), parent=self)
            return
        dialog = open_backup_manager(self, target, backup_root)
        if dialog.restored:
            self.plan = None
            self.scan_a = None
            self.scan_b = None
            self.library_a_root = None
            self.library_b_root = None
            self.last_report = None
            self.health = None
            for item in self.tree.get_children():
                self.tree.delete(item)
            self._update_controls()
            self.status_var.set("Backup restored. The previous synchronization plan was discarded; scan again before applying changes.")

    def _direction(self) -> SyncDirection:
        if not self.library_a_root or not self.library_b_root:
            raise ValueError("Scan both libraries before applying a plan.")
        master = MasterLibrary.LIBRARY_A if self.master_var.get() == "library_a" else MasterLibrary.LIBRARY_B
        return SyncDirection(self.library_a_root, self.library_b_root, master)

    def _backup_root(self) -> Path:
        value = self.backup_var.get().strip()
        if not value:
            raise ValueError("Choose a backup location before applying a modifying mode.")
        return validate_backup_root(value, (self.library_a_root, self.library_b_root)) if self.library_a_root and self.library_b_root else Path(value).expanduser()

    def _set_busy(self, busy: bool, *, cancellable_scan: bool = False) -> None:
        self.scan_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.start(12)
            self.busy_started_at = time.monotonic()
            self._tick_busy_clock()
        else:
            self.progress.stop()
            self.busy_started_at = None
            if self.busy_clock_after is not None:
                try:
                    self.after_cancel(self.busy_clock_after)
                except tk.TclError:
                    pass
                self.busy_clock_after = None
            self.elapsed_var.set("")
        self.cancel_button.configure(state="normal" if busy and cancellable_scan else "disabled")
        self._update_controls(busy)

    def _tick_busy_clock(self) -> None:
        if self.busy_started_at is None:
            return
        elapsed = max(0, int(time.monotonic() - self.busy_started_at))
        minutes, seconds = divmod(elapsed, 60)
        self.elapsed_var.set(f"{minutes:02d}:{seconds:02d}")
        self.busy_clock_after = self.after(1000, self._tick_busy_clock)

    def cancel_scan(self) -> None:
        if not self.scan_active:
            return
        self.cancel_scan_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Cancellation requested — finishing the current library scan safely…")

    def _scan_cancelled(self) -> None:
        self.scan_active = False
        self._set_busy(False)
        self.status_var.set("Scan cancelled at a safe boundary. No library files were changed.")

    def _update_controls(self, busy: bool = False) -> None:
        has_plan = self.plan is not None and self.scan_errors == 0 and bool(self.scan_a and self.scan_a.enumeration_complete) and bool(self.scan_b and self.scan_b.enumeration_complete)
        fuzzy = has_plan and any(not match.confirmed for match in self.plan.matches)
        conflicts = has_plan and any(match.metadata_conflict or match.artwork_conflict for match in self.plan.matches)
        backup_ready = bool(self.backup_var.get().strip())
        conflict_count = sum(match.metadata_conflict or match.artwork_conflict for match in self.plan.matches) if has_plan else 0
        conflict_review_incomplete = conflict_count > len(self.review_choices)
        mode = self.mode_var.get()
        mode_blocked = (mode == SyncMode.MIRROR and bool(fuzzy)) or (mode == SyncMode.RECONCILE and (bool(fuzzy) or conflict_review_incomplete))
        can_apply = has_plan and backup_ready and self.preview_ready and not mode_blocked
        for button, enabled in ((self.review_conflicts_button, conflicts), (self.review_fuzzy_button, fuzzy), (self.dry_run_button, has_plan), (self.execute_button, can_apply), (self.export_button, self.last_report is not None), (getattr(self, "health_button", None), self.health is not None)):
            if button is None:
                continue
            button.configure(state="normal" if enabled and not busy else "disabled")
        if hasattr(self, "backups_a_button"):
            self._update_backup_buttons()
        self._update_workflow()

    def _comparison_rows(self) -> list[tuple[str, str, str, str]]:
        if not self.plan:
            return []
        from harmelune.explain import explain_match
        rows: list[tuple[str, str, str, str]] = []
        for match in self.plan.matches:
            explanation = explain_match(match)
            if not match.confirmed:
                category, label = "fuzzy", "Uncertain match"
            elif match.metadata_conflict or match.artwork_conflict:
                category, label = "conflicts", "Conflict"
            else:
                category, label = "exact", "Exact / confirmed match"
            score_label = f"engine score {explanation.confidence:.0%} (not a guarantee)" if not match.confirmed else f"confidence {explanation.confidence:.0%}"
            evidence = "; ".join(explanation.reasons) or "No additional evidence recorded"
            conflicts_text = f"; conflicts: {', '.join(explanation.conflicts)}" if explanation.conflicts else ""
            details = f"A: {match.library_a.display_artist} — {match.library_a.display_title} ↔ B: {match.library_b.display_artist} — {match.library_b.display_title}; {explanation.identity}; {score_label}; evidence: {evidence}{conflicts_text}"
            rows.append((category, label, "1", details))
        for track in self.plan.library_a_only:
            rows.append(("a_only", "Only in Library A", "1", f"{track.display_artist} — {track.display_title} · {track.path}"))
        for track in self.plan.library_b_only:
            rows.append(("b_only", "Only in Library B", "1", f"{track.display_artist} — {track.display_title} · {track.path}"))
        return rows

    def _refresh_health(self) -> None:
        if self.scan_a is None or self.scan_b is None:
            for button in getattr(self, "summary_buttons", {}).values():
                button.configure(state="disabled")
            return
        self.health = build_health_report(self.scan_a, self.scan_b, self.plan)
        rows = self._comparison_rows()
        counts = comparison_counts(rows)
        labels = {"exact": "Exact matches", "a_only": "Only in A", "b_only": "Only in B", "fuzzy": "Review fuzzy", "conflicts": "Conflicts"}
        for key, button in self.summary_buttons.items():
            button.configure(text=f"{labels[key]}\n{counts[key]}", state="normal")
        for item in self.tree.get_children():
            self.tree.delete(item)
        if self.active_filter != "all" and not counts.get(self.active_filter, 0):
            self.active_filter = "all"
        visible = filter_comparison_rows(rows, self.active_filter)
        for category, label, count, details in visible:
            self.tree.insert("", "end", values=(label, count, details), tags=(category,))
        self.tree.tag_configure("fuzzy", foreground="#FFD080")
        self.tree.tag_configure("conflicts", foreground="#F49BA6")
        self.tree.tag_configure("exact", foreground="#8BD8C2")
        self._update_workflow()
        if hasattr(self, "health_button"):
            self.health_button.configure(state="normal")

    def show_health(self) -> None:
        if self.health is None:
            messagebox.showinfo("Library health", "Compare both libraries first to calculate health metrics.", parent=self)
            return
        open_health_dashboard(self, self.health)

    def filter_results(self, category: str) -> None:
        self.active_filter = category
        self._refresh_health()
        labels = {"all": "all results", "exact": "exact matches", "a_only": "tracks only in Library A", "b_only": "tracks only in Library B", "fuzzy": "uncertain matches", "conflicts": "conflicts"}
        self.status_var.set(f"Showing {labels.get(category, 'selected results')}.")

    def _workflow_title(self) -> str:
        return workflow_step(
            bool(self.library_a_var.get().strip()),
            bool(self.library_b_var.get().strip()),
            self.plan,
            self.preview_ready,
            self.review_choices,
        )

    def _update_workflow(self) -> None:
        step = self._workflow_title()
        self.workflow_var.set(step)
        if step.startswith("01"):
            help_text = "Choose two different, accessible music folders. No files are changed."
        elif step.startswith("02"):
            help_text = "Compare both libraries to build a reviewable plan. Scanning is read-only."
        elif step.startswith("03"):
            fuzzy = sum(not m.confirmed for m in self.plan.matches) if self.plan else 0
            conflicts = sum(m.metadata_conflict or m.artwork_conflict for m in self.plan.matches) if self.plan else 0
            help_text = f"Review uncertain matches ({fuzzy}) and metadata/artwork conflicts ({conflicts}) before previewing."
        elif step.startswith("04"):
            help_text = "Preview the plan first. Preview does not modify library or backup files."
        else:
            help_text = "Preview complete. Apply still requires a verified backup before modifying files."
        self.workflow_help_var.set(help_text)

    def scan(self) -> None:
        self._save_settings()
        try:
            library_a, library_b = validate_library_pair(self.library_a_var.get().strip(), self.library_b_var.get().strip())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Invalid libraries", str(exc), parent=self)
            return
        self._invalidate_scan()
        self.cancel_scan_event.clear()
        self.scan_active = True
        self._set_busy(True, cancellable_scan=True)
        self.status_var.set("Scanning Library A… cancellation is available between library scans.")
        def worker() -> None:
            try:
                result_a = scan_library(
                    library_a,
                    "a",
                    progress=lambda count: self.after(0, lambda count=count: self.status_var.set(f"Scanning Library A… {count} file(s) visited.")),
                    cancel=self.cancel_scan_event.is_set,
                )
                if self.cancel_scan_event.is_set():
                    self.after(0, self._scan_cancelled)
                    return
                self.after(0, lambda: self.status_var.set("Library A scanned. Scanning Library B…"))
                result_b = scan_library(
                    library_b,
                    "b",
                    progress=lambda count: self.after(0, lambda count=count: self.status_var.set(f"Scanning Library B… {count} file(s) visited.")),
                    cancel=self.cancel_scan_event.is_set,
                )
                if self.cancel_scan_event.is_set():
                    self.after(0, self._scan_cancelled)
                    return
                plan = build_plan(result_a, result_b, threshold=self.settings.fuzzy_threshold)
                self.after(0, lambda: self._show_scan(library_a, library_b, result_a, result_b, plan))
            except Exception as exc:
                self.after(0, lambda error=exc: self._scan_failed(error))
        threading.Thread(target=worker, daemon=True).start()

    def _show_scan(self, library_a: Path, library_b: Path, result_a, result_b, plan: SyncPlan) -> None:
        self.scan_active = False
        self.plan, self.scan_a, self.scan_b = plan, result_a, result_b
        self.preview_ready = False
        self.last_dry_run = None
        self.active_filter = "all"
        self.library_a_root, self.library_b_root = library_a, library_b
        self.scan_errors = len(result_a.errors) + len(result_b.errors)
        self.last_report = None
        self.review_choices = {}
        self._refresh_health()
        self._set_busy(False)
        if self.scan_errors or not result_a.enumeration_complete or not result_b.enumeration_complete:
            self.status_var.set(f"Scan incomplete — {self.scan_errors} issue(s). Review errors and rescan before preview/apply. Nothing was changed.")
        else:
            self.status_var.set(f"Scan complete — {len(result_a.tracks)} + {len(result_b.tracks)} tracks. Nothing was changed.")

    def _scan_failed(self, exc: Exception) -> None:
        """Surface scan worker exceptions and restore a usable UI state."""
        self.scan_active = False
        self.plan = None
        self.scan_a = None
        self.scan_b = None
        self.last_report = None
        self.review_choices = {}
        self._set_busy(False)
        self._refresh_health()
        self.status_var.set("Scan failed. Libraries were not changed.")
        messagebox.showerror("Scan failed", str(exc), parent=self)

    def review_conflicts(self) -> None:
        if not self.plan:
            return
        from harmelune.conflict_ui import review_conflicts
        conflicts = [m for m in self.plan.matches if m.metadata_conflict or m.artwork_conflict]
        choices = review_conflicts(self, conflicts)
        if choices is not None:
            self.review_choices = choices
            self.preview_ready = False
            self.last_dry_run = None
            self._refresh_health()
            self._update_controls()
            self.status_var.set(f"Saved {len(choices)} conflict decision(s).")

    def review_fuzzy(self) -> None:
        if not self.plan:
            return
        fuzzy = [m for m in self.plan.matches if not m.confirmed]
        decisions = review_fuzzy_matches(self, fuzzy)
        if decisions is not None:
            self.plan = apply_fuzzy_decisions(self.plan, decisions)
            self.preview_ready = False
            self.last_dry_run = None
            self._refresh_health()
            self.status_var.set("Fuzzy review saved. Rescan if the filesystem changes.")
            self._update_controls()

    def _reconcile_decisions(self) -> dict[str, ReconcileDecision] | None:
        if not self.plan:
            return None
        decisions: dict[str, ReconcileDecision] = {}
        for track in self.plan.library_a_only:
            answer = messagebox.askyesnocancel("Reconcile A-only track", f"Copy to Library B?\n\n{track.path}\n\nYes = Copy A → B\nNo = Skip", parent=self)
            if answer is None:
                return None
            decisions[f"a-only:{track.path}"] = ReconcileDecision.COPY_A_TO_B if answer else ReconcileDecision.SKIP
        for track in self.plan.library_b_only:
            answer = messagebox.askyesnocancel("Reconcile B-only track", f"Copy to Library A?\n\n{track.path}\n\nYes = Copy B → A\nNo = Skip", parent=self)
            if answer is None:
                return None
            decisions[f"b-only:{track.path}"] = ReconcileDecision.COPY_B_TO_A if answer else ReconcileDecision.SKIP
        for path, choice in self.review_choices.items():
            decisions[f"match:{path}"] = {ConflictChoice.LAPTOP: ReconcileDecision.KEEP_A, ConflictChoice.PHONE: ReconcileDecision.KEEP_B, ConflictChoice.SKIP: ReconcileDecision.SKIP}[choice]
        if any(not m.confirmed and f"match:{m.library_a.path}" not in decisions for m in self.plan.matches):
            return None
        if any((m.metadata_conflict or m.artwork_conflict) and f"match:{m.library_a.path}" not in decisions for m in self.plan.matches):
            return None
        return decisions

    def _operation_lines(self, operations, limit: int = 12) -> list[str]:
        lines = []
        for operation in operations[:limit]:
            raw_kind = getattr(operation, "kind", getattr(operation, "action", "operation"))
            kind = getattr(raw_kind, "value", str(raw_kind)).upper()
            source = str(operation.source) if operation.source is not None else "(no source)"
            lines.append(f"{kind}: {source}  →  {operation.destination}")
        if len(operations) > limit:
            lines.append(f"… and {len(operations) - limit} more operation(s). See the full preview list.")
        return lines

    def _show_preview_dialog(self, result, mode: str) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Synchronization plan preview")
        dialog.geometry("1040x700")
        dialog.minsize(640, 420)
        dialog.transient(self)
        self._configure_dialog_theme(dialog)
        root = ttk.Frame(dialog, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Preview · no files changed", style="Title.TLabel").pack(anchor="w")
        counts = {kind: 0 for kind in ("COPY", "REPLACE", "DELETE", "SKIPPED", "BLOCKED")}
        rows = []
        for operation in result.operations:
            raw_kind = getattr(operation, "kind", getattr(operation, "action", "operation"))
            kind = getattr(raw_kind, "value", str(raw_kind)).upper()
            counts[kind] = counts.get(kind, 0) + 1
            source = str(operation.source) if operation.source is not None else "—"
            destination = str(operation.destination)
            reason = {"COPY": "Missing in destination", "REPLACE": "Destination content differs", "DELETE": "Not present in master/source"}.get(kind, "Proposed operation")
            rows.append((kind, source, destination, reason))
        for item in result.skipped:
            counts["SKIPPED"] += 1
            rows.append(("SKIPPED", "—", str(item), "Already exists or explicitly skipped"))
        for item in result.blocked:
            counts["BLOCKED"] += 1
            rows.append(("BLOCKED", "—", str(item), "Must be resolved before apply"))
        ttk.Label(root, text=f"Mode: {mode.upper()}  ·  Copy {counts['COPY']}  ·  Replace {counts['REPLACE']}  ·  Delete {counts['DELETE']}  ·  Skip {counts['SKIPPED']}  ·  Blocked {counts['BLOCKED']}", style="Section.TLabel", wraplength=980).pack(anchor="w", pady=(4, 8))
        if mode == SyncMode.MIRROR:
            target = "Library B" if self.master_var.get() == "library_a" else "Library A"
            ttk.Label(root, text=f"MIRROR WARNING: {self.master_var.get()} is the master/source. {target} is the target and may have files replaced or deleted.", style="Danger.TLabel", wraplength=980).pack(anchor="w", pady=(0, 8))
        ttk.Label(root, text="Backup status: not created yet. Apply creates and verifies a backup before modifying files.", style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(0, 8))
        filter_row = ttk.Frame(root)
        filter_row.pack(fill="x", pady=(0, 6))
        ttk.Label(filter_row, text="Show:").pack(side="left")
        filter_var = tk.StringVar(value="All operations")
        filters = ("All operations", "COPY", "REPLACE", "DELETE", "SKIPPED", "BLOCKED")
        combo = ttk.Combobox(filter_row, textvariable=filter_var, values=filters, state="readonly", width=18)
        combo.pack(side="left", padx=(6, 0))
        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)
        columns = ("action", "source", "destination", "reason")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (("action", "Action", 95), ("source", "Source", 300), ("destination", "Destination", 300), ("reason", "Why", 220)):
            tree.heading(column, text=title)
            tree.column(column, width=width, minwidth=80, anchor="w")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        tree.tag_configure("DELETE", foreground="#F49BA6")
        tree.tag_configure("BLOCKED", foreground="#F49BA6")
        tree.tag_configure("REPLACE", foreground="#FFD080")
        def refresh_rows(*_args) -> None:
            tree.delete(*tree.get_children())
            selected = filter_var.get()
            for row in rows:
                if selected != "All operations" and row[0] != selected:
                    continue
                tree.insert("", "end", values=row, tags=(row[0],))
        combo.bind("<<ComboboxSelected>>", refresh_rows)
        refresh_rows()
        ttk.Label(root, text="Double-check delete/replace rows and destination paths. This preview is read-only.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Button(root, text="Close preview", command=dialog.destroy, style="Primary.TButton").pack(anchor="e", pady=(10, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Control-w>", lambda _event: dialog.destroy())

    def _configure_dialog_theme(self, dialog: tk.Toplevel) -> None:
        configure_theme(dialog, dialog=True)
        style = ttk.Style(dialog)
        style.configure("Danger.TLabel", background="#10131B", foreground="#F49BA6", font=("Segoe UI", 10, "bold"))

    def dry_run(self) -> None:
        if not self.plan:
            return
        try:
            direction = self._direction()
            mode = self.mode_var.get()
            if mode == SyncMode.SAFE:
                result = dry_run_safe(self.plan, direction)
            elif mode == SyncMode.RECONCILE:
                decisions = self._reconcile_decisions()
                if decisions is None:
                    raise ValueError("Every Reconcile item needs an explicit decision.")
                result = dry_run_reconcile(self.plan, decisions, self._backup_root())
            else:
                result = dry_run_mirror(self.plan, direction)
            self.last_dry_run = result
            self.preview_ready = not bool(result.blocked)
            self._update_controls()
            self._update_workflow()
            self._show_preview_dialog(result, mode)
        except Exception as exc:
            messagebox.showerror("Dry run blocked", str(exc), parent=self)

    def execute(self) -> None:
        if not self.plan:
            return
        if not self.preview_ready:
            messagebox.showwarning("Preview required", "Run Preview plan and review the proposed operations before applying changes.", parent=self)
            return
        if self.mode_var.get() == SyncMode.SAFE:
            self._execute_safe()
        elif self.mode_var.get() == SyncMode.RECONCILE:
            self._execute_reconcile()
        else:
            self._execute_mirror()

    def _execute_safe(self) -> None:
        try:
            direction, backup = self._direction(), self._backup_root()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Safe mode blocked", str(exc), parent=self)
            return
        preview = self.last_dry_run
        operations = self._operation_lines(preview.operations) if preview else ["Operation list unavailable; rerun Preview."]
        summary = f"Planned operations: {len(preview.operations) if preview else 'Unknown'}\n" + "\n".join(operations) + f"\n\nBackup: will be created and verified before changes.\n\nSafe mode only adds missing files; it does not delete or overwrite existing destination files.\n\nContinue?"
        if not messagebox.askyesno("Confirm Safe mode", summary, parent=self):
            return
        self._run_worker(lambda: report_from_safe(execute_safe(self.plan, direction, backup)))

    def _execute_reconcile(self) -> None:
        decisions = self._reconcile_decisions()
        if decisions is None:
            messagebox.showwarning("Reconcile blocked", "Every missing, conflicting, or fuzzy item needs an explicit decision.", parent=self)
            return
        try:
            backup = self._backup_root()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Reconcile blocked", str(exc), parent=self)
            return
        preview = self.last_dry_run
        operations = self._operation_lines(preview.operations) if preview else ["Operation list unavailable; rerun Preview."]
        summary = f"Planned operations: {len(preview.operations) if preview else 'Unknown'}\n" + "\n".join(operations) + f"\n\nBackup: will be created and verified before changes.\n\nReconcile applies the explicit decisions you reviewed. Continue?"
        if not messagebox.askyesno("Confirm Reconcile", summary, parent=self):
            return
        self._run_worker(lambda: report_from_reconcile(execute_reconcile(self.plan, decisions, backup)))

    def _execute_mirror(self) -> None:
        try:
            direction, backup = self._direction(), self._backup_root()
            preview = build_mirror_preview(self.plan, direction)
        except Exception as exc:
            messagebox.showerror("Mirror blocked", str(exc), parent=self)
            return
        if preview.blocked:
            messagebox.showwarning("Mirror blocked", "Resolve all fuzzy matches before Mirror execution.", parent=self)
            return
        target_name = "Library B" if self.master_var.get() == "library_a" else "Library A"
        operation_lines = self._operation_lines(preview.operations, limit=12)
        warning = (f"MIRROR MODE — DESTRUCTIVE CHANGES POSSIBLE\n\nMaster/source: {self.master_var.get()}\nTarget being conformed: {target_name}\n\nCopies: {len(preview.copies)}\nReplacements: {len(preview.replacements)}\nDeletions: {len(preview.deletions)}\n\n" + "\n".join(operation_lines) + "\n\nA verified backup will be created before changes. Files in the target that are not in the master may be deleted according to this plan.")
        if not messagebox.askokcancel("Review Mirror changes", warning, icon="warning", parent=self):
            return
        confirmation = simpledialog.askstring("Confirm Mirror", "The target library may be changed or have files deleted.\nType MIRROR exactly to continue:", parent=self)
        if confirmation is None:
            return
        self._run_worker(lambda: report_from_mirror(execute_mirror(self.plan, direction, backup, confirmation)))

    def _run_worker(self, work) -> None:
        self._set_busy(True)
        self.status_var.set("Working… cancellation is disabled during file changes so transaction rollback remains protected.")
        def worker() -> None:
            try:
                report = work()
                self.after(0, lambda: self._execution_done(report))
            except Exception as exc:
                self.after(0, lambda error=exc: self._execution_failed(error))
        threading.Thread(target=worker, daemon=True).start()

    def _execution_done(self, report: ExecutionReport) -> None:
        self.last_report = report
        self.preview_ready = False
        self.last_dry_run = None
        self._set_busy(False)
        self._refresh_health()
        self.status_var.set(f"{report.mode.title()} finished with status {report.final_status.value}.")
        messagebox.showinfo("Execution result", f"Mode: {report.mode}\nStatus: {report.final_status.value}\nAttempted: {report.attempted}\nSucceeded: {report.succeeded}\nFailed: {report.failed}\nSkipped: {report.skipped}\nRolled back: {report.rolled_back}", parent=self)

    def _execution_failed(self, exc: Exception) -> None:
        self._set_busy(False)
        self.status_var.set("Execution blocked or failed.")
        messagebox.showerror("Execution failed", str(exc), parent=self)

    def check_playlist(self) -> None:
        source = filedialog.askopenfilename(
            title="Choose an M3U or M3U8 playlist",
            filetypes=[("M3U playlists", "*.m3u *.m3u8"), ("All files", "*.*")],
        )
        if not source:
            return
        try:
            report = inspect_playlist(Path(source))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Playlist check failed", str(exc), parent=self)
            return
        if report.errors:
            messagebox.showwarning("Playlist could not be fully checked", "\n".join(report.errors), parent=self)
            return
        candidates = []
        for scan in (self.scan_a, self.scan_b):
            if scan is not None:
                candidates.extend(track.path for track in scan.tracks)
        suggestions = suggest_replacements(report, candidates)
        if not report.missing:
            messagebox.showinfo("Playlist check", f"All {len(report.entries)} playlist entries resolve to existing files. No playlist changes were made.", parent=self)
            return
        lines = []
        for entry in report.missing[:25]:
            suggested = suggestions.get(entry.line_number)
            detail = f"  → Suggested: {suggested}" if suggested else "  → No unique replacement found"
            lines.append(f"Line {entry.line_number}: {entry.raw_path}{detail}")
        if len(report.missing) > 25:
            lines.append(f"... and {len(report.missing) - 25} more missing entry/entries.")
        messagebox.showwarning(
            "Missing playlist tracks",
            f"{len(report.missing)} of {len(report.entries)} playlist entries are missing.\n\n"
            + "\n".join(lines)
            + "\n\nThis check is read-only. Review suggested replacements before making changes.",
            parent=self,
        )

    def export_report(self) -> None:
        if not self.last_report:
            return
        destination = filedialog.asksaveasfilename(
            title="Export execution report",
            defaultextension=".json",
            filetypes=[
                ("JSON report", "*.json"),
                ("CSV spreadsheet", "*.csv"),
                ("HTML report", "*.html"),
            ],
            initialfile="harmelune-execution-report.json",
        )
        if not destination:
            return
        try:
            target = Path(destination)
            redact_paths = target.suffix.lower() in {".csv", ".html", ".htm"}
            path = export_report_file(self.last_report, target, redact_paths=redact_paths)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Report export failed", str(exc), parent=self)
            return
        self.status_var.set(f"Report exported to {path}")

if __name__ == "__main__":
    HarmeluneApp().mainloop()
