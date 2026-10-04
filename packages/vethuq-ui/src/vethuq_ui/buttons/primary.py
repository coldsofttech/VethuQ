"""The primary-colour button for a window's main action."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class PrimaryButton:
    # sv_ttk's accent style is the palette's `primary` colour (see docs/PALETTE.md).
    STYLE = "Accent.TButton"

    @staticmethod
    def build(
        parent: tk.Misc, text: str, command: Callable[[], None] | None = None, width: int = 9
    ) -> ttk.Button:
        return ttk.Button(
            parent,
            text=text,
            width=width,
            style=PrimaryButton.STYLE,
            command=command if command is not None else "",
        )
