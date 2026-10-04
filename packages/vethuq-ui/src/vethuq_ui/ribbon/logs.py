"""The ribbon's Logs tab: log level and retention."""

from __future__ import annotations

import tkinter as tk

from vethuq_core.settings import LogSettings
from vethuq_core.storage import Storage

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.ribbon.tab import IconTab


class LogsTab(IconTab):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent, storage)
        group = RibbonGroup.build(self, "Logs")
        self._add_button(
            group,
            lambda: actions.show_log_field("level"),
            self.level_icon_name,
            "\N{SCROLL}",
            "Level",
        )
        self._add_button(
            group,
            lambda: actions.show_log_field("retention"),
            lambda: "logs-retention",
            "\N{CALENDAR}",
            "Retention",
        )

    def level_icon_name(self) -> str:
        level = LogSettings.get_level(self._storage)
        # A level without its own icon yet shows the plain logs-level icon.
        return self._variant("logs-level", f"logs-level-{level}", True)
