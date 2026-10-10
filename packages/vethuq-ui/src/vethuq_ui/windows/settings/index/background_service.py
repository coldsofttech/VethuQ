"""Index > Background service: install and control the service, the UI's equivalent of
`vethuq background-service`."""

from __future__ import annotations

import functools
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.background import (
    BackgroundService,
    BackgroundServiceError,
    IndexJobs,
    ServiceState,
    ServiceStatus,
)

from vethuq_ui.dialogs import show_error
from vethuq_ui.windows.settings.base import SettingsWindow


class BackgroundServiceWindow:
    TITLE = "Background Service"
    NOTE = (
        "Run indexing through a background service. Once installed, indexing from here and from "
        "'vethuq index' is queued for the service instead of starting its own worker. It is never "
        "installed for you: installing it asks which Windows account runs it, then for "
        "administrator permission and that account's password (in the window that opens). "
        "Without it, indexing runs only while this app is open or when you start it from the "
        "command line."
    )
    REFRESH_MS = 2000

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        opened = SettingsWindow.open(parent, "background-service", BackgroundServiceWindow.TITLE)
        if opened is None:
            return
        window, body = opened
        SettingsWindow.heading(body, "Background indexing service", BackgroundServiceWindow.NOTE)

        status_var = tk.StringVar()
        detail_var = tk.StringVar()
        ttk.Label(body, textvariable=status_var, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(body, textvariable=detail_var, foreground="grey", wraplength=380).pack(
            anchor=tk.W, pady=(2, 10)
        )

        account_var = tk.StringVar(value=BackgroundService.current_account())
        system_var = tk.BooleanVar(value=False)
        windows = BackgroundService.backend() == "windows"
        if windows:
            form = ttk.Frame(body)
            form.pack(fill=tk.X, pady=(0, 10))
            ttk.Label(form, text="Run as account").grid(row=0, column=0, sticky=tk.W)
            account_entry = ttk.Entry(form, textvariable=account_var, width=30)
            account_entry.grid(row=0, column=1, padx=(8, 0), sticky=tk.W)
            system_check = ttk.Checkbutton(
                form,
                text="Run as LocalSystem instead (no password; can't reach your own folders "
                "or mapped drives)",
                variable=system_var,
            )
            system_check.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        grid = ttk.Frame(body)
        grid.pack(fill=tk.X)
        buttons: dict[str, ttk.Button] = {}
        busy = {"value": False}

        def refresh(status: ServiceStatus | None = None) -> None:
            if not window.winfo_exists():
                return
            current = status or BackgroundService.status()
            installed = current.installed
            status_var.set(f"Service: {current.state}")
            queued = len(IndexJobs.queued()) if installed else 0
            detail_var.set(
                f"{queued} queued job{'s' if queued != 1 else ''}"
                + (f" - runs as {current.account}" if current.account else "")
                + (f" - data folder {current.home}" if current.home else "")
                if installed
                else ("Not installed." if current.supported else "Not supported on this system.")
            )
            free = not busy["value"] and current.supported
            state = current.state
            enabled = {
                "install": free and not installed,
                "uninstall": free and installed,
                "start": free and installed and state == ServiceState.STOPPED,
                "stop": free and installed and state != ServiceState.STOPPED,
                "restart": free and installed,
                "pause": free and installed and state == ServiceState.RUNNING,
                "resume": free and installed and state == ServiceState.PAUSED,
            }
            for action, button in buttons.items():
                button.config(state=tk.NORMAL if enabled[action] else tk.DISABLED)

        def run(action: str) -> None:
            busy["value"] = True
            refresh()
            result: dict[str, object] = {}

            def work() -> None:
                try:
                    if action == "install":
                        result["status"] = BackgroundService.perform(
                            action,
                            account=account_var.get().strip() or None,
                            system=system_var.get(),
                        )
                    else:
                        result["status"] = BackgroundService.perform(action)
                except BackgroundServiceError as exc:
                    result["error"] = str(exc)
                if window.winfo_exists():
                    window.after(0, finished)

            def finished() -> None:
                busy["value"] = False
                error = result.get("error")
                if error:
                    show_error(window, BackgroundServiceWindow.TITLE, str(error))
                    refresh()
                    return
                on_status(f"Background service: {action} done")
                on_applied()
                refresh()

            threading.Thread(target=work, name=f"service-{action}", daemon=True).start()

        labels = [
            ("install", "Install"),
            ("uninstall", "Uninstall"),
            ("start", "Start"),
            ("stop", "Stop"),
            ("restart", "Restart"),
            ("pause", "Pause"),
            ("resume", "Resume"),
        ]
        for index, (action, label) in enumerate(labels):
            button = ttk.Button(grid, text=label, width=11, command=functools.partial(run, action))
            button.grid(row=index // 4, column=index % 4, padx=2, pady=2, sticky=tk.W)
            buttons[action] = button

        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(row, text="Close", width=9, command=window.destroy).pack(side=tk.RIGHT)
        window.bind("<Escape>", lambda _event: window.destroy())

        def tick() -> None:
            if not window.winfo_exists():
                return
            if not busy["value"]:
                refresh()
            window.after(BackgroundServiceWindow.REFRESH_MS, tick)

        refresh()
        window.after(BackgroundServiceWindow.REFRESH_MS, tick)
        SettingsWindow.place(window)
