"""The ribbon-style tabbed toolbar across the top of the window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_core.storage import Storage

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.database import DatabaseTab
from vethuq_ui.ribbon.home import HomeTab
from vethuq_ui.ribbon.index import IndexTab
from vethuq_ui.ribbon.logs import LogsTab
from vethuq_ui.ribbon.ocr import OcrTab
from vethuq_ui.ribbon.search import SearchTab
from vethuq_ui.ribbon.settings import SettingsTab


class Ribbon(ttk.Notebook):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        # A native tk.Menu can't be restyled by sv_ttk (it isn't a ttk
        # widget), so instead of a dropdown menu this is a ribbon-style
        # tabbed toolbar built entirely from themed ttk widgets.
        super().__init__(parent)
        self.home_tab = HomeTab(self, actions)
        self.add(self.home_tab, text="Home")
        self.search_tab = SearchTab(self, storage, actions)
        self.add(self.search_tab, text="Search")
        self.ocr_tab = OcrTab(self, storage, actions)
        self.add(self.ocr_tab, text="OCR")
        self.index_tab = IndexTab(self, storage, actions)
        self.add(self.index_tab, text="Index")
        self.database_tab = DatabaseTab(self, storage, actions)
        self.add(self.database_tab, text="Database")
        self.logs_tab = LogsTab(self, storage, actions)
        self.add(self.logs_tab, text="Logs")
        self.settings_tab = SettingsTab(self, actions)
        self.add(self.settings_tab, text="Settings")
        self.select(self.home_tab)

        # The window and index controls drive these buttons directly.
        self.pause_resume_button = self.home_tab.pause_resume_button
        self.stop_button = self.home_tab.stop_button

    def refresh_setting_icons(self) -> None:
        """Re-read the settings that pick a button's icon and update the buttons."""
        self.search_tab.refresh_icons()
        self.ocr_tab.refresh_icons()
        self.index_tab.refresh_icons()
        self.database_tab.refresh_icons()
        self.logs_tab.refresh_icons()

    def set_delete_visible(self, visible: bool) -> None:
        """Show the Delete button while a source is selected, hide it otherwise."""
        self.home_tab.set_delete_visible(visible)
