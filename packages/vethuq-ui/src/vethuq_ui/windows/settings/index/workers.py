"""Settings > Index > Workers: how many worker threads background indexing uses,
the UI's equivalent of `vethuq settings index thread-workers`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import IndexSettings
from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.stepper import Stepper
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.reset import ResetAction


class ThreadWorkersWindow:
    TITLE = "Thread Workers"
    DISABLED = "0"
    AUTO = IndexSettings.THREAD_WORKERS_AUTO
    FIXED = "fixed"
    CHOICES = (
        (DISABLED, "Disabled", "Index one file at a time. The default."),
        (AUTO, "Auto", "Size the worker count from the CPU and memory free when a run starts."),
        (FIXED, "Fixed", "Always use this many workers:"),
    )

    @staticmethod
    def describe(value: str) -> str:
        if value == ThreadWorkersWindow.DISABLED:
            return "disabled"
        if value == ThreadWorkersWindow.AUTO:
            return "auto"
        return f"{value} workers"

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        opened = SettingsWindow.open(parent, "thread-workers", ThreadWorkersWindow.TITLE)
        if opened is None:
            return
        window, body = opened
        default = IndexSettings.DEFAULT_THREAD_WORKERS
        default_text = ThreadWorkersWindow.describe(default)
        SettingsWindow.heading(body, "How many worker threads background indexing uses")

        saved = IndexSettings.get_thread_workers(storage)
        if saved in (ThreadWorkersWindow.DISABLED, ThreadWorkersWindow.AUTO):
            mode, count = saved, 2
        else:
            mode, count = ThreadWorkersWindow.FIXED, int(saved)
        mode_var = tk.StringVar(value=mode)
        stepper = Stepper(
            body, value=count, minimum=1, maximum=IndexSettings.THREAD_WORKERS_MAX, step=1
        )

        def refresh() -> None:
            stepper.set_enabled(mode_var.get() == ThreadWorkersWindow.FIXED)

        for value, label, description in ThreadWorkersWindow.CHOICES:
            ttk.Radiobutton(body, text=label, value=value, variable=mode_var, command=refresh).pack(
                anchor=tk.W, pady=(6, 0)
            )
            ttk.Label(
                body, text=description, foreground="grey", wraplength=360, justify=tk.LEFT
            ).pack(anchor=tk.W, padx=(24, 0))
        stepper.pack(anchor=tk.W, padx=(24, 0), pady=(6, 0))
        refresh()

        def apply() -> None:
            mode = mode_var.get()
            value = str(int(stepper.value)) if mode == ThreadWorkersWindow.FIXED else mode
            try:
                IndexSettings.set_thread_workers(storage, value)
            except ValueError as exc:
                show_error(window, ThreadWorkersWindow.TITLE, str(exc))
                return
            on_status(f"Thread workers set to {ThreadWorkersWindow.describe(value)}")
            on_applied()
            window.destroy()

        buttons = SettingsWindow.buttons(window, body, apply)
        ResetAction.add(
            window,
            buttons,
            title=ThreadWorkersWindow.TITLE,
            default_label=default_text,
            is_default=lambda: IndexSettings.get_thread_workers(storage) == default,
            reset=lambda: IndexSettings.reset_thread_workers(storage),
            status=f"Thread workers reset to the default ({default_text})",
            on_status=on_status,
            on_applied=on_applied,
        )
        SettingsWindow.place(window)
