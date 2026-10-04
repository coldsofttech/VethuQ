"""A window for one settings field: its control, Apply, Cancel and a red Reset."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.fields import SettingField
from vethuq_ui.windows.settings.reset import ResetAction


class FieldWindow:
    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        key: str,
        title: str,
        storage: Storage,
        make_field: Callable[[Storage], SettingField],
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        """Open the window, or bring the already-open one to the front."""
        field = make_field(storage)
        opened = SettingsWindow.open(parent, key, title)
        if opened is None:
            return
        window, body = opened
        SettingsWindow.heading(body, field.label, field.note)
        field.build(body).pack(anchor=tk.W)

        def apply() -> None:
            try:
                field.save()
            except ValueError as exc:
                show_error(window, title, str(exc))
                return
            on_status(f"{field.status} set to {field.describe()}")
            on_applied()
            window.destroy()

        buttons = SettingsWindow.buttons(window, body, apply)
        ResetAction.add(
            window,
            buttons,
            title=title,
            default_label=field.default_words(),
            is_default=field.is_default,
            reset=field.reset_saved,
            status=f"{field.status} reset to the default ({field.default_words()})",
            on_status=on_status,
            on_applied=on_applied,
        )
        SettingsWindow.place(window)
