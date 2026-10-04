"""Settings > Index > Stability: how long a file must stay unchanged before it is indexed,
the UI's equivalent of `vethuq settings index stability-check`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from vethuq_core.settings import OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.stepper import Stepper
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.reset import ResetAction


class StabilityCheckWindow:
    TITLE = "Stability Check"
    MAX_SECONDS = 10.0
    STEP_SECONDS = 0.5

    @staticmethod
    def describe(seconds: float) -> str:
        return "off" if seconds == 0 else f"{seconds:g} s"

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        opened = SettingsWindow.open(parent, "stability-check", StabilityCheckWindow.TITLE)
        if opened is None:
            return
        window, body = opened
        default = OcrSettings.DEFAULT_STABILITY_CHECK_SECONDS
        default_text = StabilityCheckWindow.describe(default)
        SettingsWindow.heading(
            body,
            "Seconds a file must stay unchanged before it is indexed",
            "Two checks this far apart confirm a file has stopped being written to. "
            f"0 turns the check off. The default is {default_text}.",
        )
        stepper = Stepper(
            body,
            value=OcrSettings.get_stability_check_seconds(storage),
            minimum=0,
            maximum=StabilityCheckWindow.MAX_SECONDS,
            step=StabilityCheckWindow.STEP_SECONDS,
            text=lambda value: "Off" if value == 0 else f"{value:g} s",
        )
        stepper.pack(anchor=tk.W)

        def apply() -> None:
            seconds = stepper.value
            try:
                OcrSettings.set_stability_check_seconds(storage, seconds)
            except ValueError as exc:
                show_error(window, StabilityCheckWindow.TITLE, str(exc))
                return
            on_status(f"Stability check set to {StabilityCheckWindow.describe(seconds)}")
            on_applied()
            window.destroy()

        buttons = SettingsWindow.buttons(window, body, apply)
        ResetAction.add(
            window,
            buttons,
            title=StabilityCheckWindow.TITLE,
            default_label=default_text,
            is_default=lambda: OcrSettings.get_stability_check_seconds(storage) == default,
            reset=lambda: OcrSettings.reset_stability_check_seconds(storage),
            status=f"Stability check reset to the default ({default_text})",
            on_status=on_status,
            on_applied=on_applied,
        )
        SettingsWindow.place(window)
