"""The window's bottom status bar: idle/indexing text and a busy indicator."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from vethuq_core.index import IndexState


class StatusBar(ttk.Frame):
    MESSAGE_CLEAR_MS = 5000

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)

        self.message_var = tk.StringVar()
        ttk.Label(self, textvariable=self.message_var, anchor=tk.W).pack(
            side=tk.LEFT, padx=(8, 4), pady=4
        )
        self._clear_job: str | None = None

        self.var = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.var, anchor=tk.E).pack(side=tk.RIGHT, padx=(4, 8), pady=4)

        self.progress = ttk.Progressbar(self, mode="indeterminate", length=120)
        self.progress.pack(side=tk.RIGHT, pady=4)

    def show_message(self, text: str) -> None:
        """Show `text` on the left for a few seconds, replacing any earlier message."""
        if self._clear_job is not None:
            self.after_cancel(self._clear_job)
        self.message_var.set(text)
        self._clear_job = self.after(StatusBar.MESSAGE_CLEAR_MS, self._clear_message)

    def _clear_message(self) -> None:
        self._clear_job = None
        self.message_var.set("")

    def set_indexing(self, state: IndexState) -> None:
        if state.is_paused:
            self.var.set(f"Paused ({state.processed_files}/{state.total_files})")
        else:
            current = (
                f": {', '.join(Path(f).name for f in state.current_files)}"
                if state.current_files
                else ""
            )
            self.var.set(f"Indexing ({state.processed_files}/{state.total_files}){current}")
        self.progress.start(10)

    def set_idle(self) -> None:
        self.progress.stop()
        self.var.set("Idle")
