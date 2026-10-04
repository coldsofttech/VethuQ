"""The ribbon's Settings tab: GPU, Location and Help."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_core.settings import GpuSettings
from vethuq_core.storage import Storage

from vethuq_ui.dialogs import ask_yes_no
from vethuq_ui.icons import get_icon
from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.widgets import Widgets


class SettingsTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent)
        self._storage = storage
        self._show_status = actions.show_status

        ocr_group = RibbonGroup.build(self, "GPU")
        self.gpu_var = tk.BooleanVar(value=GpuSettings.is_enabled(self._storage))
        self.gpu_button = ttk.Checkbutton(
            ocr_group,
            variable=self.gpu_var,
            command=self.on_toggle_gpu,
            style="Toolbutton",
            **Widgets.icon_button_kwargs(self.gpu_icon_name(), "\N{HIGH VOLTAGE SIGN}", ""),
        )
        self.gpu_button.pack(side=tk.LEFT, padx=2)

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

    def gpu_icon_name(self) -> str:
        return "gpu" if self.gpu_var.get() else "gpu-disable"

    def on_toggle_gpu(self) -> None:
        enable = self.gpu_var.get()
        if enable:
            title, message = (
                "Enable GPU",
                "Use the GPU for OCR?\n\nIf no compatible GPU is available, "
                "VethuQ falls back to the CPU automatically.",
            )
        else:
            title, message = "Disable GPU", "Disable the GPU? OCR will run on the CPU."
        if not ask_yes_no(self.winfo_toplevel(), title, message):
            self.gpu_var.set(not enable)  # declined: keep the previous state
            return
        GpuSettings.set_enabled(self._storage, enable)
        self._show_status(
            "GPU enabled for OCR (falls back to the CPU if none is available)"
            if enable
            else "GPU disabled: OCR will run on the CPU"
        )
        icon = get_icon(self.gpu_icon_name())
        if icon is not None:
            self.gpu_button.configure(image=icon)
