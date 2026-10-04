"""A [-] value [+] control for a bounded number."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class Stepper(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        value: float,
        minimum: float,
        maximum: float,
        step: float = 1,
        text: Callable[[float], str] = lambda value: f"{value:g}",
    ) -> None:
        super().__init__(parent)
        self._value = value
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._text = text
        self._enabled = True
        self._label_var = tk.StringVar()

        self._minus = ttk.Button(self, text="\N{MINUS SIGN}", width=3, command=lambda: self._by(-1))
        self._minus.pack(side=tk.LEFT)
        self._label = ttk.Label(
            self,
            textvariable=self._label_var,
            width=7,
            anchor=tk.CENTER,
            font=("Segoe UI", 12, "bold"),
        )
        self._label.pack(side=tk.LEFT, padx=6)
        self._plus = ttk.Button(self, text="+", width=3, command=lambda: self._by(1))
        self._plus.pack(side=tk.LEFT)
        self._refresh()

    @property
    def value(self) -> float:
        return self._value

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._label.configure(foreground="" if enabled else "grey")
        self._refresh()

    def _by(self, direction: int) -> None:
        # A value saved outside the range (set from the CLI) still displays, and steps back in.
        stepped = round(self._value + direction * self._step, 6)
        self._value = max(self._minimum, min(self._maximum, stepped))
        self._refresh()

    def _refresh(self) -> None:
        self._label_var.set(self._text(self._value))
        can_down = self._enabled and self._value > self._minimum
        can_up = self._enabled and self._value < self._maximum
        self._minus.state(["!disabled"] if can_down else ["disabled"])
        self._plus.state(["!disabled"] if can_up else ["disabled"])
