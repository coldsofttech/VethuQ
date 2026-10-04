"""The ribbon's Settings tab: Help."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.widgets import Widgets


class SettingsTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, actions: RibbonActions) -> None:
        super().__init__(parent)
        help_group = RibbonGroup.build(self, "Help")
        ttk.Button(
            help_group,
            command=actions.show_about,
            **Widgets.icon_button_kwargs("about", "\N{INFORMATION SOURCE}", "About"),
        ).pack(side=tk.LEFT, padx=2)
