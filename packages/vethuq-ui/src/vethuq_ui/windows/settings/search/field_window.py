"""The Search windows opened from the Search tab: one window per search setting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from vethuq_core.storage import Storage

from vethuq_ui.windows.settings.field_window import FieldWindow
from vethuq_ui.windows.settings.fields import SettingField
from vethuq_ui.windows.settings.search.fields import SearchFields


class SearchFieldWindow:
    # The ribbon names a setting; this says which field edits it.
    FIELDS: dict[str, Callable[[Storage], SettingField]] = {
        "snippet": SearchFields.snippet,
        "export-format": SearchFields.export_format,
        "engine": SearchFields.engine,
        "fuzzy-threshold": SearchFields.fuzzy_threshold,
        "proximity-distance": SearchFields.proximity_distance,
        "noise": SearchFields.noise,
        "case": SearchFields.case,
        "leetspeak": SearchFields.leetspeak,
        "unicode": SearchFields.unicode,
    }

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        name: str,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        make_field = SearchFieldWindow.FIELDS[name]
        title = f"Search {make_field(storage).label}"
        FieldWindow.show(
            parent, f"search-{name}", title, storage, make_field, on_status, on_applied
        )
