"""What the ribbon tabs with setting buttons share: adding buttons and keeping their icons
in step with the settings."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.storage import Storage

from vethuq_ui.icons import Icons
from vethuq_ui.widgets import Widgets


class IconTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, storage: Storage) -> None:
        super().__init__(parent)
        self._storage = storage
        # Buttons whose icon follows a setting, with the function that names the icon.
        self._icon_buttons: list[tuple[ttk.Button, Callable[[], str]]] = []

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
        return variant if use_variant and Icons.get(variant) is not None else base

    def refresh_icons(self) -> None:
        """Re-read the settings that pick an icon and update their buttons."""
        for button, icon_name in self._icon_buttons:
            icon = Icons.get(icon_name())
            if icon is not None:
                button.configure(image=icon)
