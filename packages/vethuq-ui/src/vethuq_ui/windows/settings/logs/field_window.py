"""The Logs windows opened from the Logs tab: one window per logging setting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from vethuq_core.storage import Storage

from vethuq_ui.windows.settings.field_window import FieldWindow
from vethuq_ui.windows.settings.fields import SettingField
from vethuq_ui.windows.settings.logs.fields import LogFields


class LogFieldWindow:
    # The ribbon names a setting; this says which field edits it.
    FIELDS: dict[str, Callable[[Storage], SettingField]] = {
        "level": LogFields.level,
        "retention": LogFields.retention,
    }

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        name: str,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        make_field = LogFieldWindow.FIELDS[name]
        title = make_field(storage).label
        FieldWindow.show(parent, f"logs-{name}", title, storage, make_field, on_status, on_applied)
