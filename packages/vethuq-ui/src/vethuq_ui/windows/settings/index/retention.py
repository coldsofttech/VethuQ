"""Settings > Index > Retention: how long a removed source is kept before it is purged,
the UI's equivalent of `vethuq settings index removed-retention`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import SourceSettings
from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.reset import ResetAction


class RemovedRetentionWindow:
    TITLE = "Removed Source Retention"
    # Largest unit first, so a stored value shows in the biggest unit that divides it evenly.
    UNITS = (("Days", 24 * 60), ("Hours", 60), ("Minutes", 1))

    @staticmethod
    def split(minutes: int) -> tuple[int, str]:
        """`minutes` as a whole number of the largest unit that divides it evenly."""
        for name, size in RemovedRetentionWindow.UNITS:
            if minutes > 0 and minutes % size == 0:
                return minutes // size, name
        return minutes, "Minutes"

    @staticmethod
    def describe(minutes: int) -> str:
        amount, unit = RemovedRetentionWindow.split(minutes)
        return f"{amount} {unit.lower()}"

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        opened = SettingsWindow.open(parent, "removed-retention", RemovedRetentionWindow.TITLE)
        if opened is None:
            return
        window, body = opened
        default = SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES
        default_text = RemovedRetentionWindow.describe(default)
        SettingsWindow.heading(
            body,
            "How long a removed source is kept before it is purged",
            f"0 purges it straight away. The default is {default_text}.",
        )

        saved = SourceSettings.get_removed_retention_minutes(storage)
        amount, unit = RemovedRetentionWindow.split(saved)
        amount_var = tk.StringVar(value=str(amount))
        unit_var = tk.StringVar(value=unit)
        row = ttk.Frame(body)
        row.pack(anchor=tk.W)
        entry = ttk.Entry(row, textvariable=amount_var, width=8, justify=tk.RIGHT)
        entry.pack(side=tk.LEFT)
        # Radio buttons rather than a Combobox: its drop-down list is a plain Tk listbox that
        # sv_ttk cannot theme.
        for name, _size in reversed(RemovedRetentionWindow.UNITS):
            ttk.Radiobutton(row, text=name, value=name, variable=unit_var).pack(
                side=tk.LEFT, padx=(14, 0)
            )

        def apply() -> None:
            size = dict(RemovedRetentionWindow.UNITS)[unit_var.get()]
            try:
                minutes = int(amount_var.get()) * size
                SourceSettings.set_removed_retention_minutes(storage, minutes)
            except ValueError:
                show_error(window, RemovedRetentionWindow.TITLE, "Enter a whole number, 0 or more.")
                return
            text = RemovedRetentionWindow.describe(minutes)
            on_status(f"Removed source retention set to {text}")
            on_applied()
            window.destroy()

        buttons = SettingsWindow.buttons(window, body, apply)
        ResetAction.add(
            window,
            buttons,
            title=RemovedRetentionWindow.TITLE,
            default_label=default_text,
            is_default=lambda: SourceSettings.get_removed_retention_minutes(storage) == default,
            reset=lambda: SourceSettings.reset_removed_retention_minutes(storage),
            status=f"Removed source retention reset to the default ({default_text})",
            on_status=on_status,
            on_applied=on_applied,
        )
        SettingsWindow.place(window)
        entry.focus_set()
        entry.selection_range(0, tk.END)
