"""Settings > Updates: whether VethuQ checks for updates, the UI's equivalent of
`vethuq settings updates`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import UpdateSettings
from vethuq_core.storage import Storage

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.windows.placement import Placement
from vethuq_ui.windows.settings.reset import ResetAction


class UpdatesWindow:
    _open: tk.Toplevel | None = None

    CHOICES = (
        ("on", "On (default)", "Check, tell me when a newer version exists, and offer to update."),
        (
            "notify-only",
            "Notify only",
            "Check and tell me in the status bar. Never offer to update.",
        ),
        ("off", "Off", "Never check."),
    )

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        """Open the window, or bring the already-open one to the front."""
        existing = UpdatesWindow._open
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        UpdatesWindow._open = window
        window.title("Updates")
        window.resizable(False, False)
        window.transient(parent)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Check for updates", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        ttk.Label(
            body,
            text=(
                "The check reads VethuQ's signed policy file, at most once a day. That exposes "
                "your IP address to its host; your VethuQ version is not sent."
            ),
            foreground="grey",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))
        if UpdateSettings.disabled_by_environment():
            ttk.Label(
                body,
                text=f"{UpdateSettings.ENV_VAR} is set, so the check is off whatever this says.",
                wraplength=380,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(0, 8))

        value_var = tk.StringVar(value=UpdateSettings.get_check(storage))
        for value, label, detail in UpdatesWindow.CHOICES:
            ttk.Radiobutton(body, text=label, value=value, variable=value_var).pack(
                anchor=tk.W, pady=(6, 0)
            )
            ttk.Label(body, text=detail, foreground="grey", wraplength=360).pack(
                anchor=tk.W, padx=(24, 0)
            )

        hidden = ttk.Frame(body)
        hidden.pack(fill=tk.X, pady=(12, 0))
        snoozed = UpdateSettings.is_snoozed(storage)
        skipped = UpdateSettings.get_skipped_version(storage)
        if snoozed or skipped:
            parts = ["Reminders snoozed"] if snoozed else []
            if skipped:
                parts.append(f"skipping {skipped}")
            ttk.Label(hidden, text=", ".join(parts).capitalize() + ".").pack(side=tk.LEFT)

            def show_again() -> None:
                UpdateSettings.clear_snooze(storage)
                UpdateSettings.clear_skip(storage)
                on_status("Update notices will be shown again")
                on_applied()
                window.destroy()

            ttk.Button(hidden, text="Show again", command=show_again).pack(side=tk.RIGHT)

        def apply() -> None:
            UpdateSettings.set_check(storage, value_var.get())
            on_status(f"Update check: {value_var.get()}")
            on_applied()
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(buttons, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        ResetAction.add(
            window,
            buttons,
            title="Updates",
            default_label=UpdateSettings.DEFAULT_CHECK,
            is_default=lambda: UpdateSettings.get_check(storage) == UpdateSettings.DEFAULT_CHECK,
            reset=lambda: UpdateSettings.reset_check(storage),
            status="Update check reset to the default (on)",
            on_status=on_status,
            on_applied=on_applied,
        )
        window.bind("<Return>", lambda _event: apply())
        window.bind("<Escape>", lambda _event: window.destroy())
        Placement.center_on_main(window)
        window.focus_set()
