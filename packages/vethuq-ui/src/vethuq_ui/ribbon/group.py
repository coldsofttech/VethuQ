"""The captioned button group shared by the ribbon's tabs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_ui.icons import get_icon


class RibbonGroup:
    @staticmethod
    def build(
        tab: ttk.Frame, caption: str, launcher: Callable[[], None] | None = None
    ) -> ttk.Frame:
        """A ribbon group: a row for its buttons, with a caption label below. With a
        `launcher`, a small arrow at the caption's right opens the group's full settings, like
        the dialog launcher on an Office ribbon group."""
        group = ttk.Frame(tab)
        group.pack(side=tk.LEFT, padx=4, pady=(4, 0))
        buttons_row = ttk.Frame(group)
        buttons_row.pack(side=tk.TOP)
        caption_row = ttk.Frame(group)
        caption_row.pack(side=tk.TOP, fill=tk.X, pady=(2, 4))
        ttk.Label(caption_row, text=caption, anchor=tk.CENTER, foreground="grey").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        if launcher is not None:
            icon = get_icon("group-launcher", 12)
            options = {"image": icon} if icon is not None else {"text": "↘"}
            ttk.Button(caption_row, command=launcher, style="Toolbutton", **options).pack(
                side=tk.RIGHT
            )
        return buttons_row
