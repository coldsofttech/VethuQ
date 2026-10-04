"""The ribbon-style tabbed toolbar across the top of the window."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from vethuq_core.settings import GpuSettings
from vethuq_core.storage import Storage

from vethuq_ui.icons import Brand, get_icon
from vethuq_ui.widgets import Widgets


@dataclass(frozen=True)
class RibbonActions:
    """What the ribbon's buttons do - supplied by the window, which owns the views."""

    show_search: Callable[[], None]
    add_folder: Callable[[], None]
    add_file: Callable[[], None]
    show_source_list: Callable[[], None]
    toggle_pause_resume: Callable[[], None]
    stop: Callable[[], None]
    delete_source: Callable[[], None]


class Ribbon(ttk.Notebook):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        # A native tk.Menu can't be restyled by sv_ttk (it isn't a ttk
        # widget), so instead of a dropdown menu this is a ribbon-style
        # tabbed toolbar built entirely from themed ttk widgets.
        super().__init__(parent)
        self._storage = storage

        home_tab = ttk.Frame(self)
        self.add(home_tab, text="Home")
        logo = Brand.logo(36)
        if logo is not None:
            logo_label = ttk.Label(home_tab, image=logo)
            logo_label.pack(side=tk.RIGHT, padx=10, pady=2)
        ttk.Button(
            home_tab,
            command=actions.show_search,
            **Widgets.icon_button_kwargs("search", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Search"),
        ).pack(side=tk.LEFT, padx=6, pady=4)

        ttk.Separator(home_tab, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        sources_group = self._build_group(home_tab, "Sources")
        ttk.Button(
            sources_group,
            command=actions.add_folder,
            **Widgets.icon_button_kwargs("folder", "\N{FILE FOLDER}", "Folder"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            sources_group,
            command=actions.add_file,
            **Widgets.icon_button_kwargs("file", "\N{PAGE FACING UP}", "File"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            sources_group,
            command=actions.show_source_list,
            **Widgets.icon_button_kwargs("list", "\N{CARD INDEX DIVIDERS}", "List"),
        ).pack(side=tk.LEFT, padx=2)
        self.pause_resume_button = ttk.Button(
            sources_group,
            command=actions.toggle_pause_resume,
            state=tk.DISABLED,
            **Widgets.icon_button_kwargs("pause", "\N{DOUBLE VERTICAL BAR}", "Pause"),
        )
        self.pause_resume_button.pack(side=tk.LEFT, padx=2)
        self.stop_button = ttk.Button(
            sources_group,
            command=actions.stop,
            state=tk.DISABLED,
            **Widgets.icon_button_kwargs("stop", "\N{BLACK SQUARE FOR STOP}", "Stop"),
        )
        self.stop_button.pack(side=tk.LEFT, padx=2)
        self.delete_button = ttk.Button(
            sources_group,
            command=actions.delete_source,
            **Widgets.icon_button_kwargs("delete", "\N{WASTEBASKET}", "Delete"),
        )

        settings_tab = ttk.Frame(self)
        self.add(settings_tab, text="Settings")

        ocr_group = self._build_group(settings_tab, "GPU")
        self.gpu_var = tk.BooleanVar(value=GpuSettings.is_enabled(self._storage))
        self.gpu_button = ttk.Checkbutton(
            ocr_group,
            variable=self.gpu_var,
            command=self.on_toggle_gpu,
            style="Toolbutton",
            **Widgets.icon_button_kwargs(self.gpu_icon_name(), "\N{HIGH VOLTAGE SIGN}", ""),
        )
        self.gpu_button.pack(side=tk.LEFT, padx=2)

        self.select(home_tab)

    @staticmethod
    def _build_group(ribbon: ttk.Frame, caption: str) -> ttk.Frame:
        """A ribbon group: a row for its buttons, with a caption label below."""
        group = ttk.Frame(ribbon)
        group.pack(side=tk.LEFT, padx=4, pady=(4, 0))
        buttons_row = ttk.Frame(group)
        buttons_row.pack(side=tk.TOP)
        ttk.Label(group, text=caption, anchor=tk.CENTER, foreground="grey").pack(
            side=tk.TOP, fill=tk.X, pady=(2, 4)
        )
        return buttons_row

    def gpu_icon_name(self) -> str:
        return "gpu" if self.gpu_var.get() else "gpu-disable"

    def on_toggle_gpu(self) -> None:
        GpuSettings.set_enabled(self._storage, self.gpu_var.get())
        icon = get_icon(self.gpu_icon_name())
        if icon is not None:
            self.gpu_button.configure(image=icon)

    def set_delete_visible(self, visible: bool) -> None:
        """Show the Delete button while a source is selected, hide it otherwise."""
        if visible:
            if not self.delete_button.winfo_ismapped():
                self.delete_button.pack(side=tk.LEFT, padx=2)
        else:
            self.delete_button.pack_forget()
