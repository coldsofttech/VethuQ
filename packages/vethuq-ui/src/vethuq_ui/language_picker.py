"""The widget for choosing OCR languages, shared by the settings and add-source windows."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_core.languages import Languages

from vethuq_ui.languages import LanguageChoice


class LanguagePicker(ttk.Frame):
    """`Automatic` (every installed language, detected per file) or a ticked set of languages."""

    def __init__(self, parent: tk.Misc, value: str | None) -> None:
        super().__init__(parent)
        current = LanguageChoice.selection_ids(value)
        self._auto = tk.BooleanVar(value=not current)
        self._ticks = {
            lang.id: tk.BooleanVar(value=lang.id in current) for lang in Languages.enabled()
        }
        ttk.Radiobutton(
            self,
            text="Automatic - detect the language of each file",
            value=True,
            variable=self._auto,
            command=self._sync,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            self, text="These languages only:", value=False, variable=self._auto, command=self._sync
        ).pack(anchor=tk.W, pady=(6, 0))
        self._boxes = []
        for lang in Languages.enabled():
            box = ttk.Checkbutton(
                self, text=LanguageChoice.label(lang.id), variable=self._ticks[lang.id]
            )
            box.pack(anchor=tk.W, padx=(24, 0))
            self._boxes.append(box)
        self._sync()

    def _sync(self) -> None:
        state = "disabled" if self._auto.get() else "normal"
        for box in self._boxes:
            box.configure(state=state)

    def chosen(self) -> list[str]:
        return [language_id for language_id, var in self._ticks.items() if var.get()]

    def is_valid(self) -> bool:
        return self._auto.get() or bool(self.chosen())

    def value(self) -> str:
        return LanguageChoice.stored(self._auto.get(), self.chosen())
