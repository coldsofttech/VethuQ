"""The ribbon's Home tab: search and the sources group."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_ui.icons import Brand
from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.widgets import Widgets


class HomeTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, actions: RibbonActions) -> None:
        super().__init__(parent)
        logo = Brand.logo(36)
        if logo is not None:
            logo_label = ttk.Label(self, image=logo)
            logo_label.pack(side=tk.RIGHT, padx=10, pady=2)
        ttk.Button(
            self,
            command=actions.show_search,
            **Widgets.icon_button_kwargs("search", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Search"),
        ).pack(side=tk.LEFT, padx=6, pady=4)

        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        sources_group = RibbonGroup.build(self, "Sources")
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

    def set_delete_visible(self, visible: bool) -> None:
        """Show the Delete button while a source is selected, hide it otherwise."""
        if visible:
            if not self.delete_button.winfo_ismapped():
                self.delete_button.pack(side=tk.LEFT, padx=2)
        else:
            self.delete_button.pack_forget()
