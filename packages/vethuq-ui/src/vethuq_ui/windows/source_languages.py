"""The languages a newly added source is read in, asked when more than one language is enabled."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_core.settings import OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.language_picker import LanguagePicker
from vethuq_ui.windows.placement import Placement


class SourceLanguagesDialog:
    @staticmethod
    def ask(parent: tk.Tk | tk.Toplevel, storage: Storage, what: str) -> str | None:
        """Ask which languages `what` (a path, or `3 files`) is read in. Returns the value to
        store (`auto`, `te`, `en,te`), or None if the person cancelled."""
        window = tk.Toplevel(parent)
        window.title("Languages")
        window.resizable(False, False)
        window.transient(parent)
        result: list[str] = []

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=f"Languages to read {what} in", font=("Segoe UI", 9, "bold")).pack(
            anchor=tk.W
        )
        ttk.Label(
            body,
            text="You can change this later; Automatic follows Settings > OCR > Languages.",
            foreground="grey",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))
        picker = LanguagePicker(body, OcrSettings.get_languages(storage))
        picker.pack(anchor=tk.W)

        def accept() -> None:
            if not picker.is_valid():
                return
            result.append(picker.value())
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(buttons, "Add", accept).pack(side=tk.RIGHT, padx=(0, 6))
        window.bind("<Return>", lambda _event: accept())
        window.bind("<Escape>", lambda _event: window.destroy())
        Placement.center_on(window, parent)
        window.grab_set()
        window.wait_window()
        return result[0] if result else None
