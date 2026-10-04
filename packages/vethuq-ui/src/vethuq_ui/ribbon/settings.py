"""The ribbon's Settings tab: OCR, Location and Help."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_core.settings import GpuSettings, OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.icons import get_icon
from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.widgets import Widgets


class SettingsTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent)
        self._storage = storage

        ocr_group = RibbonGroup.build(self, "OCR")
        self.gpu_button = ttk.Button(
            ocr_group,
            command=actions.show_gpu,
            **Widgets.icon_button_kwargs(self.gpu_icon_name(), "⚡", "GPU"),
        )
        self.gpu_button.pack(side=tk.LEFT, padx=2)
        self.retry_button = ttk.Button(
            ocr_group,
            command=actions.show_ocr_retry,
            **Widgets.icon_button_kwargs(self.retry_icon_name(), "↺", "Retry"),
        )
        self.retry_button.pack(side=tk.LEFT, padx=2)
        self.engine_button = ttk.Button(
            ocr_group,
            command=actions.show_ocr_engine,
            **Widgets.icon_button_kwargs(self.engine_icon_name(), "⚙", "Engine"),
        )
        self.engine_button.pack(side=tk.LEFT, padx=2)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

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

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        help_group = RibbonGroup.build(self, "Help")
        ttk.Button(
            help_group,
            command=actions.show_about,
            **Widgets.icon_button_kwargs("about", "\N{INFORMATION SOURCE}", "About"),
        ).pack(side=tk.LEFT, padx=2)

    def retry_icon_name(self) -> str:
        retrying = OcrSettings.get_retry_attempts(self._storage) > 0
        # Until ocr-retry-disable.png exists, keep showing the normal icon.
        if retrying or get_icon("ocr-retry-disable") is None:
            return "ocr-retry"
        return "ocr-retry-disable"

    def engine_icon_name(self) -> str:
        return f"ocr-engine-{OcrSettings.get_engine(self._storage)}"

    def gpu_icon_name(self) -> str:
        return "gpu" if GpuSettings.is_enabled(self._storage) else "gpu-disable"

    def refresh_icons(self) -> None:
        """Re-read the GPU, retry and engine settings and update their buttons' icons."""
        for button, name in (
            (self.gpu_button, self.gpu_icon_name()),
            (self.retry_button, self.retry_icon_name()),
            (self.engine_button, self.engine_icon_name()),
        ):
            icon = get_icon(name)
            if icon is not None:
                button.configure(image=icon)
