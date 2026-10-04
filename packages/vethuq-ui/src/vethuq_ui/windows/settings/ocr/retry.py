"""Settings > OCR > Retry: how many times a file's OCR is retried after a transient failure,
the UI's equivalent of `vethuq settings ocr retry`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.windows.placement import Placement
from vethuq_ui.windows.settings.reset import ResetAction


class OcrRetryWindow:
    MAX_ATTEMPTS = 10

    _open: tk.Toplevel | None = None

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        """Open the window, or bring the already-open one to the front."""
        existing = OcrRetryWindow._open
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        OcrRetryWindow._open = window
        window.title("OCR Retry")
        window.resizable(False, False)
        window.transient(parent)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text="Times to retry a file's OCR after a transient failure",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            body,
            text="0 turns retrying off. The default is "
            f"{OcrSettings.DEFAULT_RETRY_ATTEMPTS}.",
            foreground="grey",
        ).pack(anchor=tk.W, pady=(2, 0))

        attempts_var = tk.IntVar(value=OcrSettings.get_retry_attempts(storage))
        stepper = ttk.Frame(body)
        stepper.pack(anchor=tk.W, pady=(12, 0))
        minus_button = ttk.Button(stepper, text="−", width=3)
        minus_button.pack(side=tk.LEFT)
        ttk.Label(
            stepper,
            textvariable=attempts_var,
            width=4,
            anchor=tk.CENTER,
            font=("Segoe UI", 12, "bold"),
        ).pack(side=tk.LEFT, padx=6)
        plus_button = ttk.Button(stepper, text="+", width=3)
        plus_button.pack(side=tk.LEFT)

        def step(delta: int) -> None:
            attempts_var.set(max(0, min(OcrRetryWindow.MAX_ATTEMPTS, attempts_var.get() + delta)))
            refresh_buttons()

        def refresh_buttons() -> None:
            # A value saved above the maximum (set from the CLI) can still be stepped down.
            minus_button.state(["disabled"] if attempts_var.get() <= 0 else ["!disabled"])
            plus_button.state(
                ["disabled"] if attempts_var.get() >= OcrRetryWindow.MAX_ATTEMPTS else ["!disabled"]
            )

        minus_button.configure(command=lambda: step(-1))
        plus_button.configure(command=lambda: step(1))
        refresh_buttons()

        def apply() -> None:
            attempts = attempts_var.get()
            try:
                OcrSettings.set_retry_attempts(storage, attempts)
            except ValueError as exc:
                show_error(window, "OCR Retry", str(exc))
                return
            on_status(f"OCR retry attempts set to {attempts}")
            on_applied()
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(buttons, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        default = OcrSettings.DEFAULT_RETRY_ATTEMPTS
        ResetAction.add(
            window,
            buttons,
            title="OCR Retry",
            default_label=str(default),
            is_default=lambda: OcrSettings.get_retry_attempts(storage) == default,
            reset=lambda: OcrSettings.reset_retry_attempts(storage),
            status=f"OCR retry attempts reset to the default ({default})",
            on_status=on_status,
            on_applied=on_applied,
        )
        window.bind("<Return>", lambda _event: apply())
        window.bind("<Escape>", lambda _event: window.destroy())
        Placement.center_on_main(window)
