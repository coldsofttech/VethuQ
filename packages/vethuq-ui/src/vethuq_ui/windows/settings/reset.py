"""The red Reset button shared by the settings windows."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_ui.dialogs import ask_yes_no, show_error
from vethuq_ui.widgets import Widgets


class ResetAction:
    @staticmethod
    def add(
        window: tk.Toplevel,
        buttons: tk.Misc,
        *,
        title: str,
        default_label: str,
        is_default: Callable[[], bool],
        reset: Callable[[], None],
        status: str,
        on_status: Callable[[str], None],
        on_applied: Callable[[], None],
    ) -> ttk.Button:
        """Pack a red Reset button into `buttons`. It is disabled while the setting is already
        the default; otherwise it asks first, resets, reports `status` and closes `window`."""

        def click() -> None:
            if not ask_yes_no(window, title, f"Reset to the default ({default_label})?"):
                return
            try:
                reset()
            except (ValueError, OSError) as exc:
                show_error(window, title, f"Could not reset: {exc}")
                return
            on_status(status)
            on_applied()
            window.destroy()

        button = Widgets.danger_button(buttons, "Reset")
        button.configure(command=click)
        Widgets.set_danger_enabled(button, not is_default())
        button.pack(side=tk.RIGHT, padx=(0, 6))
        return button
