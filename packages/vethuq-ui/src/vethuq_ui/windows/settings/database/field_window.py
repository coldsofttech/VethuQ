"""The Database windows opened from the Settings tab: one window per database setting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from vethuq_core.storage import Storage

from vethuq_ui.windows.settings.database.fields import DbFields
from vethuq_ui.windows.settings.field_window import FieldWindow
from vethuq_ui.windows.settings.fields import SettingField


class DatabaseFieldWindow:
    # The ribbon names a setting; this says which field edits it.
    FIELDS: dict[str, Callable[[Storage], SettingField]] = {
        "integrity-check": DbFields.integrity_check,
        "integrity-check-interval": DbFields.integrity_check_interval,
        "backup": DbFields.backup,
        "backup-interval": DbFields.backup_interval,
        "backup-retention": DbFields.backup_retention,
    }

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        name: str,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        make_field = DatabaseFieldWindow.FIELDS[name]
        title = make_field(storage).label
        FieldWindow.show(parent, f"db-{name}", title, storage, make_field, on_status, on_applied)
