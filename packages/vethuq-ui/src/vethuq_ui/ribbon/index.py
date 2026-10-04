"""The ribbon's Index tab: retention, stability, workers and stale lock."""

from __future__ import annotations

import tkinter as tk

from vethuq_core.settings import IndexSettings, OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.ribbon.tab import IconTab


class IndexTab(IconTab):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent, storage)
        group = RibbonGroup.build(self, "Index")
        self._add_button(
            group,
            actions.show_removed_retention,
            lambda: "removed-retention",
            "\N{WASTEBASKET}",
            "Retention",
        )
        self._add_button(
            group,
            actions.show_stability_check,
            self.stability_icon_name,
            "\N{HOURGLASS WITH FLOWING SAND}",
            "Stability",
        )
        self._add_button(
            group,
            actions.show_thread_workers,
            self.workers_icon_name,
            "\N{TWISTED RIGHTWARDS ARROWS}",
            "Workers",
        )
        self._add_button(
            group,
            actions.show_stale_lock,
            self.stale_lock_icon_name,
            "\N{OPEN LOCK}",
            "Stale lock",
        )

    def stability_icon_name(self) -> str:
        off = OcrSettings.get_stability_check_seconds(self._storage) == 0
        return self._variant("stability-check", "stability-check-disable", off)

    def workers_icon_name(self) -> str:
        value = IndexSettings.get_thread_workers(self._storage)
        if value == IndexSettings.THREAD_WORKERS_AUTO:
            return self._variant("thread-workers", "thread-workers-auto", True)
        return self._variant("thread-workers", "thread-workers-disable", value == "0")

    def stale_lock_icon_name(self) -> str:
        off = IndexSettings.get_stale_lock(self._storage) == "disable"
        return self._variant("stale-lock", "stale-lock-disable", off)
