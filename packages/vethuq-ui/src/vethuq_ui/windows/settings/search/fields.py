"""The search settings as editable fields, shared by the single-setting windows and the full
Search settings window. Each field knows how to show itself, read what the user chose, save it
and go back to its default."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage

from vethuq_ui.stepper import Stepper


class SearchField:
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


class ChoiceField(SearchField):
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


class NumberField(SearchField):
    """A whole number with a [-] value [+] stepper."""

    def __init__(
        self,
        *args: object,
        minimum: int,
        maximum: int,
        step: int,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
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

    def reset_form(self) -> None:
        if self._stepper is not None:
            self._stepper.set(int(self.default))


class SearchFields:
    """Builds each field for one open window (a field holds that window's Tk variables)."""

    SNIPPET_MAX = 500
    SNIPPET_STEP = 10

    @staticmethod
    def snippet(storage: Storage) -> NumberField:
        return NumberField(
            storage,
            "Snippet",
            "Characters of context shown on each side of a match. 0 shows only the match.",
            "Search snippet",
            str(SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS),
            SearchSettings.get_snippet_context_chars,
            lambda s, v: SearchSettings.set_snippet_context_chars(s, int(v)),
            SearchSettings.reset_snippet_context_chars,
            minimum=0,
            maximum=SearchFields.SNIPPET_MAX,
            step=SearchFields.SNIPPET_STEP,
        )

    @staticmethod
    def export_format(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Export format",
            "The format an export is written in when none is chosen.",
            "Export format",
            SearchSettings.DEFAULT_EXPORT_FORMAT,
            SearchSettings.get_export_format,
            SearchSettings.set_export_format,
            SearchSettings.reset_export_format,
            choices=[(value, value.upper()) for value in SearchSettings.EXPORT_FORMATS],
        )

    @staticmethod
    def engine(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Engine",
            "The search engine used when none is chosen. 'all' runs every engine and ranks "
            "the pages together.",
            "Search engine",
            SearchSettings.DEFAULT_ENGINE,
            SearchSettings.get_engine,
            SearchSettings.set_engine,
            SearchSettings.reset_engine,
            choices=[(value, value) for value in SearchSettings.ENGINES],
            columns=4,
        )

    @staticmethod
    def fuzzy_threshold(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Fuzzy threshold",
            "How close a word must be to your query for the fuzzy engine to match it.",
            "Fuzzy threshold",
            SearchSettings.DEFAULT_FUZZY_THRESHOLD,
            SearchSettings.get_fuzzy_threshold_setting,
            SearchSettings.set_fuzzy_threshold,
            SearchSettings.reset_fuzzy_threshold,
            choices=[(name, name) for name in SearchSettings.FUZZY_PRESETS],
            custom_label="Custom (% or 0-1)",
        )

    @staticmethod
    def proximity_distance(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Proximity distance",
            "Most words allowed between your first and last word for the proximity engine.",
            "Proximity distance",
            SearchSettings.DEFAULT_PROXIMITY_DISTANCE,
            SearchSettings.get_proximity_distance_setting,
            SearchSettings.set_proximity_distance,
            SearchSettings.reset_proximity_distance,
            choices=[(name, name) for name in SearchSettings.PROXIMITY_PRESETS],
            custom_label=f"Custom (1-{SearchSettings.PROXIMITY_MAX_DISTANCE} words)",
        )

    @staticmethod
    def noise(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Noise level",
            "How much stray punctuation and whitespace the noise-fuzzy engine skips.",
            "Noise level",
            SearchSettings.DEFAULT_NOISE,
            SearchSettings.get_noise_level,
            SearchSettings.set_noise_level,
            SearchSettings.reset_noise_level,
            choices=[(name, name) for name in SearchSettings.NOISE_LEVELS],
        )

    @staticmethod
    def case(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Case",
            "Whether upper and lower case are the same. 'auto' uses each engine's own default.",
            "Case handling",
            SearchSettings.NORMALIZE_AUTO,
            SearchSettings.get_case,
            SearchSettings.set_case,
            SearchSettings.reset_case,
            choices=[(value, value) for value in SearchSettings.CASE_VALUES],
        )

    @staticmethod
    def leetspeak(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Leetspeak",
            "Whether look-alike characters (3 for e, @ for a) count as the letters.",
            "Leetspeak handling",
            SearchSettings.NORMALIZE_AUTO,
            SearchSettings.get_leetspeak,
            SearchSettings.set_leetspeak,
            SearchSettings.reset_leetspeak,
            choices=[(value, value) for value in SearchSettings.LEETSPEAK_VALUES],
            columns=5,
        )

    @staticmethod
    def unicode(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Unicode",
            "Whether characters written differently count as the same (café, cafe).",
            "Unicode handling",
            SearchSettings.NORMALIZE_AUTO,
            SearchSettings.get_unicode,
            SearchSettings.set_unicode,
            SearchSettings.reset_unicode,
            choices=[(value, value) for value in SearchSettings.UNICODE_VALUES],
            columns=4,
        )
