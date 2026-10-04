"""The ribbon's Database tab: integrity check, backup and where the data is kept."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import DbSettings
from vethuq_core.storage import Storage

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.ribbon.tab import IconTab
from vethuq_ui.widgets import Widgets


class DatabaseTab(IconTab):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent, storage)

        def add(
            group: ttk.Frame, name: str, icon: Callable[[], str], glyph: str, caption: str
        ) -> None:
            self._add_button(group, lambda: actions.show_db_field(name), icon, glyph, caption)

        integrity = RibbonGroup.build(self, "Integrity")
        add(integrity, "integrity-check", self.integrity_icon_name, "\N{SHIELD}", "Check")
        add(
            integrity,
            "integrity-check-interval",
            lambda: "db-integrity-interval",
            "\N{STOPWATCH}",
            "Interval",
        )

        self._separator()

        backup = RibbonGroup.build(self, "Backup")
        add(backup, "backup", self.backup_icon_name, "\N{FLOPPY DISK}", "Auto backup")
        add(
            backup,
            "backup-interval",
            lambda: "db-backup-interval",
            "\N{STOPWATCH}",
            "Interval",
        )
        add(
            backup,
            "backup-retention",
            lambda: "db-backup-retention",
            "\N{CALENDAR}",
            "Retention",
        )

        self._separator()

        location = RibbonGroup.build(self, "Location")
        ttk.Button(
            location,
            command=actions.show_app_location,
            **Widgets.icon_button_kwargs("app-location", "\N{FILE FOLDER}", "App folder"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            location,
            command=actions.show_backups_location,
            **Widgets.icon_button_kwargs("db-bkp-location", "\N{FLOPPY DISK}", "Backup folder"),
        ).pack(side=tk.LEFT, padx=2)

    def integrity_icon_name(self) -> str:
        mode = DbSettings.get_integrity_check(self._storage)
        if mode == "auto":
            return self._variant("db-integrity", "db-integrity-auto", True)
        return self._variant("db-integrity", "db-integrity-disable", mode == "disable")

    def backup_icon_name(self) -> str:
        off = DbSettings.get_backup(self._storage) == "disable"
        return self._variant("db-backup", "db-backup-disable", off)
