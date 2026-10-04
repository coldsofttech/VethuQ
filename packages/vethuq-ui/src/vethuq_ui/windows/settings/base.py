"""What every settings window shares: a single instance, the frame, and the button row."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.windows.placement import Placement


class SettingsWindow:
    _open: dict[str, tk.Toplevel] = {}

    @staticmethod
    def open(
        parent: tk.Tk | tk.Toplevel, key: str, title: str
    ) -> tuple[tk.Toplevel, ttk.Frame] | None:
        """A new window and its padded body, or None after raising the one already open."""
        existing = SettingsWindow._open.get(key)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return None
        window = tk.Toplevel(parent)
        SettingsWindow._open[key] = window
        window.title(title)
        window.resizable(False, False)
        window.transient(parent)
        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        return window, body

    @staticmethod
    def heading(body: ttk.Frame, title: str, note: str | None = None) -> None:
        ttk.Label(body, text=title, font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        if note:
            ttk.Label(
                body, text=note, foreground="grey", wraplength=380, justify=tk.LEFT
            ).pack(anchor=tk.W, pady=(2, 8))

    @staticmethod
    def buttons(window: tk.Toplevel, body: ttk.Frame, apply: Callable[[], None]) -> ttk.Frame:
        """The Cancel and Apply row. Add a Reset button to the returned frame, then `place`."""
        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(row, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(row, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        window.bind("<Return>", lambda _event: apply())
        window.bind("<Escape>", lambda _event: window.destroy())
        return row

    @staticmethod
    def place(window: tk.Toplevel) -> None:
        Placement.center_on_main(window)
        window.focus_set()
