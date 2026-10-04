"""Settings > OCR > Engine: how thoroughly OCR looks for rotated text,
the UI's equivalent of `vethuq settings ocr engine`."""

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


class OcrEngineWindow:
    DESCRIPTIONS = {
        "quick": "Reads upright text only. The fastest, and enough for most documents.",
        "moderate": (
            "Also reads text rotated by 90, 180 and 270 degrees, such as sideways or "
            "upside-down pages. Slower."
        ),
        "deep": (
            "Also reads text at every 15 degrees in between, such as a photo of a page "
            "taken at an angle. The slowest, and the most thorough."
        ),
    }

    _open: tk.Toplevel | None = None

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        """Open the window, or bring the already-open one to the front."""
        existing = OcrEngineWindow._open
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        OcrEngineWindow._open = window
        window.title("OCR Engine")
        window.resizable(False, False)
        window.transient(parent)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body, text="How thoroughly OCR looks for rotated text", font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W)
        ttk.Label(
            body,
            text=(
                "Files already indexed are brought up to the new level "
                "the next time indexing runs."
            ),
            foreground="grey",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))

        mode_var = tk.StringVar(value=OcrSettings.get_engine(storage))
        for mode in OcrSettings.ENGINE_MODES:
            ttk.Radiobutton(body, text=mode.capitalize(), value=mode, variable=mode_var).pack(
                anchor=tk.W, pady=(6, 0)
            )
            ttk.Label(
                body,
                text=OcrEngineWindow.DESCRIPTIONS.get(mode, ""),
                foreground="grey",
                wraplength=360,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, padx=(24, 0))

        def apply() -> None:
            mode = mode_var.get()
            try:
                OcrSettings.set_engine(storage, mode)
            except ValueError as exc:
                show_error(window, "OCR Engine", str(exc))
                return
            on_status(f"OCR engine set to {mode}")
            on_applied()
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(buttons, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        default = OcrSettings.DEFAULT_ENGINE
        ResetAction.add(
            window,
            buttons,
            title="OCR Engine",
            default_label=default,
            is_default=lambda: OcrSettings.get_engine(storage) == default,
            reset=lambda: OcrSettings.reset_engine(storage),
            status=f"OCR engine reset to the default ({default})",
            on_status=on_status,
            on_applied=on_applied,
        )
        window.bind("<Return>", lambda _event: apply())
        window.bind("<Escape>", lambda _event: window.destroy())
        Placement.center_on_main(window)
        window.focus_set()
