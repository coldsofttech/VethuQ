"""A lightweight hover tooltip for ttk.Treeview rows."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class TreeviewTooltip:
    """Shows a small popup with per-row text when hovering over `tree`.

    `text_for` is called with the hovered row's iid and should return the
    text to show, or a falsy value to show nothing for that row.
    """

    def __init__(self, tree: ttk.Treeview, text_for: Callable[[str], str | None]) -> None:
        self._tree = tree
        self._text_for = text_for
        self._popup: tk.Toplevel | None = None
        self._current_row: str | None = None
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<Leave>", lambda event: self._hide())

    def _on_motion(self, event: tk.Event) -> None:
        row = self._tree.identify_row(event.y)
        if row == self._current_row:
            self._reposition(event)
            return
        self._current_row = row
        self._hide()
        if not row:
            return
        text = self._text_for(row)
        if text:
            self._show(event, text)

    def _show(self, event: tk.Event, text: str) -> None:
        self._popup = tk.Toplevel(self._tree)
        self._popup.wm_overrideredirect(True)
        self._popup.wm_attributes("-topmost", True)
        tk.Label(
            self._popup,
            text=text,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            padx=4,
            pady=2,
        ).pack()
        self._reposition(event)

    def _reposition(self, event: tk.Event) -> None:
        if self._popup is None:
            return
        x = self._tree.winfo_rootx() + event.x + 16
        y = self._tree.winfo_rooty() + event.y + 10
        self._popup.wm_geometry(f"+{x}+{y}")

    def _hide(self) -> None:
        if self._popup is not None:
            self._popup.destroy()
            self._popup = None
