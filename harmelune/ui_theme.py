from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#10131B"
PANEL = "#171B27"
FIELD = "#1A1F2C"
BUTTON = "#252B40"
BUTTON_HOVER = "#343D59"
TEXT = "#E7EAF4"
MUTED = "#AAB3C8"
ACCENT = "#B7C0FF"
DANGER = "#F49BA6"
SUCCESS = "#8BD8C2"
WARNING = "#FFD080"


def configure_theme(root: tk.Misc, *, dialog: bool = False) -> None:
    """Apply Harmelune's shared high-contrast navy/lavender ttk palette."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(background=BG)
    style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Title.TLabel", background=BG, foreground="#F4F5FC", font=("Segoe UI", 20 if dialog else 22, "bold"))
    style.configure("Section.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
    style.configure("TButton", background=BUTTON, foreground=TEXT, padding=(10, 7), borderwidth=0, focuscolor=ACCENT)
    style.map("TButton", background=[("active", BUTTON_HOVER), ("disabled", "#1A1F2C")], foreground=[("disabled", "#7E879B")])
    style.configure("Primary.TButton", background=ACCENT, foreground="#171A29", font=("Segoe UI", 10, "bold"), padding=(12, 8))
    style.map("Primary.TButton", background=[("active", "#D0D5FF"), ("disabled", "#373B50")])
    style.configure("Danger.TButton", background="#6B303E", foreground="#FFF0F2", padding=(10, 7))
    style.map("Danger.TButton", background=[("active", "#843D4C")])
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, bordercolor="#343B52", padding=6)
    style.configure("TCombobox", fieldbackground=FIELD, background=BUTTON, foreground=TEXT, arrowcolor=ACCENT, padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=30, borderwidth=0, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background=BUTTON, foreground=ACCENT, font=("Segoe UI", 9, "bold"), padding=7)
    style.map("Treeview", background=[("selected", BUTTON_HOVER)], foreground=[("selected", "#FFFFFF")])
    style.configure("TLabelframe", background=BG, foreground=ACCENT)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
    style.configure("Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT, bordercolor=FIELD, lightcolor=ACCENT, darkcolor=ACCENT)
