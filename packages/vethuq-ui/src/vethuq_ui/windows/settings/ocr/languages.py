"""Settings > OCR > Languages: which languages files are read in unless a source says otherwise,
the UI's equivalent of `vethuq settings ocr languages`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.dialogs import show_error
from vethuq_ui.language_picker import LanguagePicker
from vethuq_ui.windows.placement import Placement
from vethuq_ui.windows.settings.reset import ResetAction


class OcrLanguagesWindow:
    _open: tk.Toplevel | None = None

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        """Open the window, or bring the already-open one to the front."""
        existing = OcrLanguagesWindow._open
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        OcrLanguagesWindow._open = window
        window.title("OCR Languages")
        window.resizable(False, False)
        window.transient(parent)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Languages files are read in", font=("Segoe UI", 9, "bold")).pack(
            anchor=tk.W
        )
        ttk.Label(
            body,
            text=(
                "A source can choose its own languages. With several languages, English reads "
                "each file first and the others are queued for files it does not read well."
            ),
            foreground="grey",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))
        picker = LanguagePicker(body, OcrSettings.get_languages(storage))
        picker.pack(anchor=tk.W)

        def apply() -> None:
            if not picker.is_valid():
                show_error(
                    window, "OCR Languages", "Tick at least one language, or choose Automatic."
                )
                return
            try:
                stored = OcrSettings.set_languages(storage, picker.value())
            except ValueError as exc:
                show_error(window, "OCR Languages", str(exc))
                return
            on_status(f"OCR languages set to {stored}")
            on_applied()
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(buttons, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        default = OcrSettings.DEFAULT_LANGUAGES
        ResetAction.add(
            window,
            buttons,
            title="OCR Languages",
            default_label=default,
            is_default=lambda: OcrSettings.get_languages(storage) == default,
            reset=lambda: OcrSettings.reset_languages(storage),
            status=f"OCR languages reset to the default ({default})",
            on_status=on_status,
            on_applied=on_applied,
        )
        window.bind("<Escape>", lambda _event: window.destroy())
        Placement.center_on_main(window)
        window.focus_set()
