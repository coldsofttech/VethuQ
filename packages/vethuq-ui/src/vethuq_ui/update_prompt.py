"""Tells the user a newer VethuQ exists, once at startup, in the way their setting asks for.

`on` shows a dialog; `notify-only` shows a message in the status bar. Both come from the saved
policy only, so nothing here touches the network or delays startup, and a failure is silent.
Installing the update from the app is not part of this yet; the dialog only tells.
"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from vethuq_core.storage import Storage
from vethuq_core.updates import UpdateChecker

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.logging import UiLogging
from vethuq_ui.update_plan import UpdatePlan
from vethuq_ui.windows.placement import Placement

_logger = UiLogging.logger


class UpdatePrompt:
    POLL_MS = 500
    MAX_POLLS = 12  # wait up to about 6 seconds for the background policy refresh

    @staticmethod
    def start(
        window: tk.Tk,
        storage: Storage,
        on_status: Callable[[str], None],
        refresh: threading.Thread | None,
    ) -> None:
        """Wait (without blocking) for the startup policy refresh, then tell the user if needed.

        The first look is scheduled, not run here, so a dialog never opens while the window is
        still being built.
        """
        window.after(
            UpdatePrompt.POLL_MS,
            partial(UpdatePrompt._poll, window, storage, on_status, refresh, 0),
        )

    @staticmethod
    def _poll(
        window: tk.Tk,
        storage: Storage,
        on_status: Callable[[str], None],
        refresh: threading.Thread | None,
        waited: int,
    ) -> None:
        try:
            if refresh is not None and refresh.is_alive() and waited < UpdatePrompt.MAX_POLLS:
                window.after(
                    UpdatePrompt.POLL_MS,
                    partial(UpdatePrompt._poll, window, storage, on_status, refresh, waited + 1),
                )
                return
            result = UpdateChecker.status(storage, _logger)
            plan = UpdatePlan.for_result(result)
            if plan is None:
                return
            if plan.kind == "message":
                on_status(plan.message)
                return
            UpdatePlan.apply(storage, result, UpdatePrompt.ask(window, plan), on_status)
        except Exception:  # noqa: BLE001 - an update notice must never get in the way
            _logger.warning("Update notice failed", exc_info=True)

    @staticmethod
    def ask(parent: tk.Tk, plan: UpdatePlan) -> str:
        """Show the dialog and return the chosen action (the first choice if it is just closed)."""
        dialog = tk.Toplevel(parent)
        dialog.title(plan.title)
        dialog.resizable(False, False)
        dialog.transient(parent)
        dialog.grab_set()
        chosen = {"action": plan.choices[0][0]}

        def close(action: str) -> None:
            chosen["action"] = action
            dialog.destroy()

        body = ttk.Frame(dialog, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=plan.message, wraplength=360, justify=tk.LEFT).pack(anchor=tk.W)
        if plan.release_notes_url:
            notes = ttk.Button(
                body,
                text="Release notes",
                command=partial(webbrowser.open, plan.release_notes_url),
            )
            notes.pack(anchor=tk.W, pady=(10, 0))

        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=(16, 0))
        for index, (action, label) in enumerate(reversed(plan.choices)):
            command = partial(close, action)
            if index == len(plan.choices) - 1:
                PrimaryButton.build(row, label, command, width=0).pack(side=tk.RIGHT, padx=(6, 0))
            else:
                ttk.Button(row, text=label, command=command).pack(side=tk.RIGHT, padx=(6, 0))
        dialog.protocol("WM_DELETE_WINDOW", partial(close, plan.choices[0][0]))
        Placement.center_on_main(dialog)
        dialog.wait_window()
        return chosen["action"]
