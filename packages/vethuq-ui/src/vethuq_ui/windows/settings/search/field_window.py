"""A window for one search setting: Snippet, Export format or Engine from the ribbon."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from vethuq_core.storage import Storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.reset import ResetAction
from vethuq_ui.windows.settings.search.fields import SearchField, SearchFields


class SearchFieldWindow:
    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        key: str,
        storage: Storage,
        make_field: Callable[[Storage], SearchField],
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        field = make_field(storage)
        opened = SettingsWindow.open(parent, key, f"Search {field.label}")
        if opened is None:
            return
        window, body = opened
        SettingsWindow.heading(body, field.label, field.note)
        field.build(body).pack(anchor=tk.W)

        def apply() -> None:
            try:
                field.save()
            except ValueError as exc:
                show_error(window, f"Search {field.label}", str(exc))
                return
            on_status(f"{field.status} set to {field.pending()}")
            on_applied()
            window.destroy()

        buttons = SettingsWindow.buttons(window, body, apply)
        ResetAction.add(
            window,
            buttons,
            title=f"Search {field.label}",
            default_label=field.default,
            is_default=field.is_default,
            reset=field.reset_saved,
            status=f"{field.status} reset to the default ({field.default})",
            on_status=on_status,
            on_applied=on_applied,
        )
        SettingsWindow.place(window)

    @staticmethod
    def snippet(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None],
        on_applied: Callable[[], None],
    ) -> None:
        SearchFieldWindow.show(
            parent, "search-snippet", storage, SearchFields.snippet, on_status, on_applied
        )

    @staticmethod
    def export_format(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None],
        on_applied: Callable[[], None],
    ) -> None:
        SearchFieldWindow.show(
            parent,
            "search-export-format",
            storage,
            SearchFields.export_format,
            on_status,
            on_applied,
        )

    @staticmethod
    def engine(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None],
        on_applied: Callable[[], None],
    ) -> None:
        SearchFieldWindow.show(
            parent, "search-engine", storage, SearchFields.engine, on_status, on_applied
        )
