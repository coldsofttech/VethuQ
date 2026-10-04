"""The captioned button group shared by the ribbon's tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class RibbonGroup:
    @staticmethod
    def build(tab: ttk.Frame, caption: str | None) -> ttk.Frame:
        """A ribbon group: a row for its buttons, with a caption label below. A group with no
        `caption` shows just its buttons, for a tab that already says what it holds."""
        group = ttk.Frame(tab)
        group.pack(side=tk.LEFT, padx=4, pady=(4, 0))
        buttons_row = ttk.Frame(group)
        buttons_row.pack(side=tk.TOP)
        if caption is not None:
            ttk.Label(group, text=caption, anchor=tk.CENTER, foreground="grey").pack(
                side=tk.TOP, fill=tk.X, pady=(2, 4)
            )
        return buttons_row
