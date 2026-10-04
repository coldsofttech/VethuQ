"""The full Search settings window, opened from the Search group's launcher arrow."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.storage import Storage

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.dialogs import ask_yes_no, show_error
from vethuq_ui.widgets import Widgets
from vethuq_ui.windows.settings.base import SettingsWindow
from vethuq_ui.windows.settings.search.fields import SearchField, SearchFields


class SearchSettingsWindow:
    TITLE = "Search Settings"

    @staticmethod
    def tabs(storage: Storage) -> list[tuple[str, list[SearchField]]]:
        return [
            ("Results", [SearchFields.snippet(storage), SearchFields.export_format(storage)]),
            (
                "Matching",
                [
                    SearchFields.engine(storage),
                    SearchFields.fuzzy_threshold(storage),
                    SearchFields.proximity_distance(storage),
                    SearchFields.noise(storage),
                ],
            ),
            (
                "Normalization",
                [
                    SearchFields.case(storage),
                    SearchFields.leetspeak(storage),
                    SearchFields.unicode(storage),
                ],
            ),
        ]

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        opened = SettingsWindow.open(parent, "search-settings", SearchSettingsWindow.TITLE)
        if opened is None:
            return
        window, body = opened
        tabs = SearchSettingsWindow.tabs(storage)
        fields = [field for _name, group in tabs for field in group]

        notebook = ttk.Notebook(body)
        notebook.pack(fill=tk.BOTH, expand=True)
        for name, group in tabs:
            page = ttk.Frame(notebook, padding=(12, 8))
            notebook.add(page, text=name)
            for field in group:
                SearchSettingsWindow._row(page, field)

        def apply() -> None:
            saved = 0
            for field in fields:
                if not field.changed():
                    continue
                try:
                    field.save()
                except ValueError as exc:
                    show_error(window, SearchSettingsWindow.TITLE, f"{field.label}: {exc}")
                    return
                saved += 1
            if saved:
                on_status(f"Saved {saved} search setting{'s' if saved != 1 else ''}")
                on_applied()
            window.destroy()

        def reset_all() -> None:
            if not ask_yes_no(
                window, SearchSettingsWindow.TITLE, "Reset every search setting to its default?"
            ):
                return
            for field in fields:
                field.reset_saved()
            on_status("Search settings reset to the defaults")
            on_applied()
            window.destroy()

        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(row, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(row, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        reset_button = Widgets.danger_button(row, "Reset all")
        reset_button.configure(command=reset_all)
        reset_button.pack(side=tk.RIGHT, padx=(0, 6))
        window.bind("<Return>", lambda _event: apply())
        window.bind("<Escape>", lambda _event: window.destroy())
        SettingsWindow.place(window)

    @staticmethod
    def _row(page: ttk.Frame, field: SearchField) -> None:
        """A heading with the field's own Reset (back to the default in the form, not saved
        until Apply), its note and its control."""
        head = ttk.Frame(page)
        head.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(head, text=field.label, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Button(head, text="Reset", width=7, command=field.reset_form).pack(side=tk.RIGHT)
        ttk.Label(
            page, text=field.note, foreground="grey", wraplength=460, justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 4))
        field.build(page).pack(anchor=tk.W)
