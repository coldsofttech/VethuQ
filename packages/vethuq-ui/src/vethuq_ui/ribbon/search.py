"""The ribbon's Search tab: one button for each search setting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.ribbon.tab import IconTab
from vethuq_ui.widgets import Widgets


class SearchTab(IconTab):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent, storage)

        def add(
            group: ttk.Frame, name: str, icon: Callable[[], str], glyph: str, caption: str
        ) -> None:
            self._add_button(group, lambda: actions.show_search_field(name), icon, glyph, caption)

        search = RibbonGroup.build(self, "Search")
        ttk.Button(
            search,
            command=actions.show_search,
            **Widgets.icon_button_kwargs("search", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Search"),
        ).pack(side=tk.LEFT, padx=2)

        self._separator()

        results = RibbonGroup.build(self, "Results")
        add(results, "snippet", self.snippet_icon_name, "\N{MEMO}", "Snippet")
        add(
            results,
            "export-format",
            self.export_format_icon_name,
            "\N{FLOPPY DISK}",
            "Export",
        )

        self._separator()

        engine = RibbonGroup.build(self, "Engine")
        add(
            engine,
            "engine",
            self.engine_icon_name,
            "\N{LEFT-POINTING MAGNIFYING GLASS}",
            "Engine",
        )

        self._separator()

        tolerance = RibbonGroup.build(self, "Tolerance")
        add(
            tolerance,
            "fuzzy-threshold",
            lambda: "search-fuzzy-threshold",
            "\N{LEFT RIGHT ARROW}",
            "Fuzzy",
        )
        add(
            tolerance,
            "proximity-distance",
            lambda: "search-proximity-distance",
            "\N{LEFT RIGHT ARROW}",
            "Proximity",
        )
        add(tolerance, "noise", lambda: "search-noise", "\N{MUSICAL NOTE}", "Noise")

        self._separator()

        normalize = RibbonGroup.build(self, "Normalize")
        add(normalize, "case", lambda: "search-case", "Aa", "Case")
        add(normalize, "leetspeak", self.leetspeak_icon_name, "\N{DIGIT THREE}", "Leetspeak")
        add(
            normalize,
            "unicode",
            self.unicode_icon_name,
            "\N{GLOBE WITH MERIDIANS}",
            "Unicode",
        )

    def snippet_icon_name(self) -> str:
        off = SearchSettings.get_snippet_context_chars(self._storage) == 0
        return self._variant("search-snippet", "search-snippet-disable", off)

    def export_format_icon_name(self) -> str:
        return f"export-format-{SearchSettings.get_export_format(self._storage)}"

    def engine_icon_name(self) -> str:
        engine = SearchSettings.get_engine(self._storage)
        # An engine without its own icon yet shows the plain search-engine icon.
        return self._variant("search-engine", f"search-engine-{engine}", True)

    def leetspeak_icon_name(self) -> str:
        off = SearchSettings.get_leetspeak(self._storage) == SearchSettings.LEETSPEAK_OFF
        return self._variant("search-leetspeak", "search-leetspeak-disable", off)

    def unicode_icon_name(self) -> str:
        off = SearchSettings.get_unicode(self._storage) == "off"
        return self._variant("search-unicode", "search-unicode-disable", off)
