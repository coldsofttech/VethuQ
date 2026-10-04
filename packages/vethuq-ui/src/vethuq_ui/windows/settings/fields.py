"""Editable settings fields shared by the settings windows. Each field knows how to show
itself, read what the user chose, save it and go back to its default."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.storage import Storage

from vethuq_ui.stepper import Stepper


class SettingField:
    """One search setting. Subclasses draw the control; this holds what they have in common."""

    def __init__(
        self,
        storage: Storage,
        label: str,
        note: str,
        status: str,
        default: str,
        get: Callable[[Storage], object],
        set_: Callable[[Storage, str], None],
        reset: Callable[[Storage], None],
    ) -> None:
        self.storage = storage
        self.label = label
        self.note = note
        self.status = status
        self.default = default
        self._get = get
        self._set = set_
        self._reset = reset

    def build(self, parent: tk.Misc) -> ttk.Frame:
        raise NotImplementedError

    def pending(self) -> str:
        """The value as it stands in the form right now."""
        raise NotImplementedError

    def reset_form(self) -> None:
        """Put the form back to the default, without saving."""
        raise NotImplementedError

    def describe(self) -> str:
        """The form's value in words, for the status message."""
        return self.pending()

    def default_words(self) -> str:
        """The default in words, for a reset confirmation or message."""
        return self.default

    def saved(self) -> str:
        return str(self._get(self.storage))

    def changed(self) -> bool:
        return self.pending() != self.saved()

    def is_default(self) -> bool:
        return self.saved() == self.default

    def save(self) -> None:
        """Store the form's value. Raises `ValueError` when it is not allowed."""
        self._set(self.storage, self.pending())

    def reset_saved(self) -> None:
        self._reset(self.storage)


class ChoiceField(SettingField):
    """Pick one of a few values with radio buttons, optionally with a free-form value too."""

    CUSTOM = "\x00custom"

    def __init__(
        self,
        *args: object,
        choices: list[tuple[str, str]],
        columns: int | None = None,
        custom_label: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._choices = choices
        self._columns = columns or len(choices)
        self._custom_label = custom_label
        self._values = {value for value, _label in choices}
        self.var = tk.StringVar()
        self.custom_var = tk.StringVar()
        self._custom_entry: ttk.Entry | None = None
        self._show(self.saved())

    def _show(self, value: str) -> None:
        if value in self._values or self._custom_label is None:
            self.var.set(value)
            self.custom_var.set("")
        else:
            self.var.set(ChoiceField.CUSTOM)
            self.custom_var.set(value)

    def build(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent)
        for index, (value, label) in enumerate(self._choices):
            radio = ttk.Radiobutton(
                frame, text=label, value=value, variable=self.var, command=self._sync
            )
            radio.grid(
                row=index // self._columns,
                column=index % self._columns,
                sticky=tk.W,
                padx=(0, 14),
            )
        if self._custom_label is not None:
            row = len(self._choices) // self._columns + 1
            custom = ttk.Frame(frame)
            custom.grid(row=row, column=0, columnspan=self._columns, sticky=tk.W, pady=(4, 0))
            ttk.Radiobutton(
                custom,
                text=self._custom_label,
                value=ChoiceField.CUSTOM,
                variable=self.var,
                command=self._sync,
            ).pack(side=tk.LEFT)
            self._custom_entry = ttk.Entry(custom, textvariable=self.custom_var, width=8)
            self._custom_entry.pack(side=tk.LEFT, padx=(8, 0))
        self._sync()
        return frame

    def _sync(self) -> None:
        if self._custom_entry is not None:
            custom = self.var.get() == ChoiceField.CUSTOM
            self._custom_entry.state(["!disabled"] if custom else ["disabled"])

    def pending(self) -> str:
        if self.var.get() == ChoiceField.CUSTOM:
            return self.custom_var.get().strip().lower()
        return self.var.get()

    def reset_form(self) -> None:
        self._show(self.default)
        self._sync()


class NumberField(SettingField):
    """A whole number with a [-] value [+] stepper."""

    def __init__(
        self,
        *args: object,
        minimum: int,
        maximum: int,
        step: int,
        unit: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._unit = unit
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._stepper: Stepper | None = None

    def build(self, parent: tk.Misc) -> ttk.Frame:
        self._stepper = Stepper(
            parent,
            value=int(self.saved()),
            minimum=self._minimum,
            maximum=self._maximum,
            step=self._step,
        )
        return self._stepper

    def pending(self) -> str:
        return str(int(self._stepper.value)) if self._stepper is not None else self.saved()

    def describe(self) -> str:
        return f"{self.pending()} {self._unit}".strip()

    def default_words(self) -> str:
        return f"{self.default} {self._unit}".strip()

    def reset_form(self) -> None:
        if self._stepper is not None:
            self._stepper.set(int(self.default))


class DurationField(SettingField):
    """A whole number of minutes, entered as an amount in minutes, hours or days."""

    UNITS = (("Days", 24 * 60), ("Hours", 60), ("Minutes", 1))

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.amount_var = tk.StringVar()
        self.unit_var = tk.StringVar()
        self._show(int(self.saved()))

    @staticmethod
    def split(minutes: int) -> tuple[int, str]:
        """`minutes` as a whole number of the largest unit that divides it evenly."""
        for name, size in DurationField.UNITS:
            if minutes > 0 and minutes % size == 0:
                return minutes // size, name
        return minutes, "Minutes"

    @staticmethod
    def words(minutes: int) -> str:
        amount, unit = DurationField.split(minutes)
        name = unit.lower()
        return f"{amount} {name[:-1] if amount == 1 else name}"

    def _show(self, minutes: int) -> None:
        amount, unit = DurationField.split(minutes)
        self.amount_var.set(str(amount))
        self.unit_var.set(unit)

    def build(self, parent: tk.Misc) -> ttk.Frame:
        row = ttk.Frame(parent)
        ttk.Entry(row, textvariable=self.amount_var, width=8, justify=tk.RIGHT).pack(side=tk.LEFT)
        for name, _size in reversed(DurationField.UNITS):
            ttk.Radiobutton(row, text=name, value=name, variable=self.unit_var).pack(
                side=tk.LEFT, padx=(14, 0)
            )
        return row

    def pending(self) -> str:
        """The form as minutes; raises `ValueError` when the amount is not a whole number."""
        size = dict(DurationField.UNITS)[self.unit_var.get()]
        try:
            return str(int(self.amount_var.get()) * size)
        except ValueError:
            raise ValueError("Enter a whole number of minutes, hours or days.") from None

    def describe(self) -> str:
        return DurationField.words(int(self.pending()))

    def default_words(self) -> str:
        return DurationField.words(int(self.default))

    def changed(self) -> bool:
        try:
            return self.pending() != self.saved()
        except ValueError:
            return True  # let save() report what is wrong

    def reset_form(self) -> None:
        self._show(int(self.default))
