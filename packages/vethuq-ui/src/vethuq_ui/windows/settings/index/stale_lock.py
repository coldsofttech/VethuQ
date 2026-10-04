"""Settings > Index > Stale lock: what happens to a lock left behind by a run that did not exit
cleanly, the UI's equivalent of `vethuq settings index stale-lock`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import IndexSettings
from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.reset import ResetAction


class StaleLockWindow:
    TITLE = "Stale Lock"
    DESCRIPTIONS = {
        "auto": "Clear it automatically on the next run. The default.",
        "enable": "Clear it automatically on the next run, as an explicit opt-in.",
        "disable": "Keep it, and require --force to start a run, as before.",
    }

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        opened = SettingsWindow.open(parent, "stale-lock", StaleLockWindow.TITLE)
        if opened is None:
            return
        window, body = opened
        default = IndexSettings.DEFAULT_STALE_LOCK
        SettingsWindow.heading(body, "A lock left behind by a run that did not exit cleanly")

        value_var = tk.StringVar(value=IndexSettings.get_stale_lock(storage))
        for value in IndexSettings.STALE_LOCK_VALUES:
            ttk.Radiobutton(body, text=value.capitalize(), value=value, variable=value_var).pack(
                anchor=tk.W, pady=(6, 0)
            )
            ttk.Label(
                body,
                text=StaleLockWindow.DESCRIPTIONS.get(value, ""),
                foreground="grey",
                wraplength=360,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, padx=(24, 0))

        def apply() -> None:
            value = value_var.get()
            try:
                IndexSettings.set_stale_lock(storage, value)
            except ValueError as exc:
                show_error(window, StaleLockWindow.TITLE, str(exc))
                return
            on_status(f"Stale lock handling set to {value}")
            on_applied()
            window.destroy()

        buttons = SettingsWindow.buttons(window, body, apply)
        ResetAction.add(
            window,
            buttons,
            title=StaleLockWindow.TITLE,
            default_label=default,
            is_default=lambda: IndexSettings.get_stale_lock(storage) == default,
            reset=lambda: IndexSettings.reset_stale_lock(storage),
            status=f"Stale lock handling reset to the default ({default})",
            on_status=on_status,
            on_applied=on_applied,
        )
        SettingsWindow.place(window)
