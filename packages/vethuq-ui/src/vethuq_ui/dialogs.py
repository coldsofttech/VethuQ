"""sv_ttk-themed replacements for `tkinter.messagebox`.

`messagebox` opens a native OS dialog that ttk styles (sv_ttk included) can't
reach, so its buttons/background stay classic-Tk gray even though the rest of
the app is Windows 11 styled. These build the same yes/no/error/warning
dialogs from plain ttk widgets instead, so they pick up the active theme.
"""

from __future__ import annotations

import tkinter as tk
from functools import partial
from tkinter import ttk

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.widgets import Widgets
from vethuq_ui.windows.placement import Placement


def _show(
    parent: tk.Tk | tk.Toplevel,
    title: str,
    message: str,
    buttons: list[tuple[str, bool]],
    primary: str | None = None,
    danger: str | None = None,
) -> bool:
    """`buttons` is [(label, return_value), ...]; the first is the default. The buttons labelled
    `primary` and `danger` are drawn in those colours."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    result = {"value": buttons[-1][1]}

    def close(value: bool) -> None:
        result["value"] = value
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16)
    body.pack(fill=tk.BOTH, expand=True)
    ttk.Label(body, text=message, wraplength=320, justify=tk.LEFT).pack(anchor=tk.W)

    button_row = ttk.Frame(body)
    button_row.pack(fill=tk.X, pady=(16, 0))
    for label, value in reversed(buttons):
        if label == primary:
            button = PrimaryButton.build(button_row, label, partial(close, value), width=0)
        elif label == danger:
            button = Widgets.danger_button(button_row, label)
            button.configure(command=partial(close, value), width=0)
        else:
            button = ttk.Button(button_row, text=label, command=partial(close, value))
        button.pack(side=tk.RIGHT, padx=(6, 0))

    dialog.protocol("WM_DELETE_WINDOW", partial(close, buttons[-1][1]))
    Placement.center_on_main(dialog)

    dialog.wait_window()
    return result["value"]


def ask_yes_no(parent: tk.Tk | tk.Toplevel, title: str, message: str) -> bool:
    return _show(parent, title, message, [("Yes", True), ("No", False)], primary="Yes", danger="No")


def show_error(parent: tk.Tk | tk.Toplevel, title: str, message: str) -> None:
    _show(parent, title, message, [("OK", True)])


def show_warning(parent: tk.Tk | tk.Toplevel, title: str, message: str) -> None:
    _show(parent, title, message, [("OK", True)])
