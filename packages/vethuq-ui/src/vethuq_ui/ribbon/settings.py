"""The ribbon's Settings tab: OCR, Index, Search, Location and Help."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import GpuSettings, IndexSettings, OcrSettings, SearchSettings
from vethuq_core.storage import Storage

from vethuq_ui.icons import get_icon
from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.widgets import Widgets


class SettingsTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent)
        self._storage = storage
        # Buttons whose icon follows a setting, with the function that names the icon.
        self._icon_buttons: list[tuple[ttk.Button, Callable[[], str]]] = []

        ocr_group = RibbonGroup.build(self, "OCR")
        self._add_button(
            ocr_group, actions.show_gpu, self.gpu_icon_name, "\N{HIGH VOLTAGE SIGN}", "GPU"
        )
        self._add_button(
            ocr_group,
            actions.show_ocr_retry,
            self.retry_icon_name,
            "\N{ANTICLOCKWISE OPEN CIRCLE ARROW}",
            "Retry",
        )
        self._add_button(
            ocr_group, actions.show_ocr_engine, self.engine_icon_name, "\N{GEAR}", "Engine"
        )

        self._separator()

        index_group = RibbonGroup.build(self, "Index")
        self._add_button(
            index_group,
            actions.show_removed_retention,
            lambda: "removed-retention",
            "\N{WASTEBASKET}",
            "Retention",
        )
        self._add_button(
            index_group,
            actions.show_stability_check,
            self.stability_icon_name,
            "\N{HOURGLASS WITH FLOWING SAND}",
            "Stability",
        )
        self._add_button(
            index_group,
            actions.show_thread_workers,
            self.workers_icon_name,
            "\N{TWISTED RIGHTWARDS ARROWS}",
            "Workers",
        )
        self._add_button(
            index_group,
            actions.show_stale_lock,
            self.stale_lock_icon_name,
            "\N{OPEN LOCK}",
            "Stale lock",
        )

        self._separator()

        search_group = RibbonGroup.build(self, "Search", launcher=actions.show_search_settings)
        self._add_button(
            search_group,
            actions.show_search_export_format,
            self.export_format_icon_name,
            "\N{FLOPPY DISK}",
            "Export",
        )
        self._add_button(
            search_group,
            actions.show_search_engine,
            self.search_engine_icon_name,
            "\N{LEFT-POINTING MAGNIFYING GLASS}",
            "Engine",
        )
        self._add_button(
            search_group,
            actions.show_search_snippet,
            self.snippet_icon_name,
            "\N{MEMO}",
            "Snippet",
        )

        self._separator()

        location_group = RibbonGroup.build(self, "Location")
        ttk.Button(
            location_group,
            command=actions.show_app_location,
            **Widgets.icon_button_kwargs("app-location", "\N{FILE FOLDER}", "App"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            location_group,
            command=actions.show_backups_location,
            **Widgets.icon_button_kwargs("db-bkp-location", "\N{FLOPPY DISK}", "Backups"),
        ).pack(side=tk.LEFT, padx=2)

        self._separator()

        help_group = RibbonGroup.build(self, "Help")
        ttk.Button(
            help_group,
            command=actions.show_about,
            **Widgets.icon_button_kwargs("about", "\N{INFORMATION SOURCE}", "About"),
        ).pack(side=tk.LEFT, padx=2)

    def _separator(self) -> None:
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

    def _add_button(
        self,
        group: ttk.Frame,
        command: Callable[[], None],
        icon_name: Callable[[], str],
        glyph: str,
        caption: str,
    ) -> None:
        button = ttk.Button(
            group, command=command, **Widgets.icon_button_kwargs(icon_name(), glyph, caption)
        )
        button.pack(side=tk.LEFT, padx=2)
        self._icon_buttons.append((button, icon_name))

    @staticmethod
    def _variant(base: str, variant: str, use_variant: bool) -> str:
        """`variant` when asked for and its icon exists yet; otherwise the plain `base` icon."""
        return variant if use_variant and get_icon(variant) is not None else base

    def retry_icon_name(self) -> str:
        off = OcrSettings.get_retry_attempts(self._storage) == 0
        return self._variant("ocr-retry", "ocr-retry-disable", off)

    def engine_icon_name(self) -> str:
        return f"ocr-engine-{OcrSettings.get_engine(self._storage)}"

    def gpu_icon_name(self) -> str:
        return "gpu" if GpuSettings.is_enabled(self._storage) else "gpu-disable"

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

    def export_format_icon_name(self) -> str:
        return f"export-format-{SearchSettings.get_export_format(self._storage)}"

    def search_engine_icon_name(self) -> str:
        engine = SearchSettings.get_engine(self._storage)
        # An engine without its own icon yet shows the plain search-engine icon.
        return self._variant("search-engine", f"search-engine-{engine}", True)

    def snippet_icon_name(self) -> str:
        off = SearchSettings.get_snippet_context_chars(self._storage) == 0
        return self._variant("search-snippet", "search-snippet-disable", off)

    def refresh_icons(self) -> None:
        """Re-read the settings that pick an icon and update their buttons."""
        for button, icon_name in self._icon_buttons:
            icon = get_icon(icon_name())
            if icon is not None:
                button.configure(image=icon)
