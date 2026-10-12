"""The filter bar of an HTML export: one dropdown of checkboxes per facet, and what each row has."""

from __future__ import annotations

import html
import json
from collections.abc import Callable


class _Facets:
    @staticmethod
    def bar(
        definitions: list[tuple[str, str]],
        rows: list[dict[str, list[str]]],
        tag: Callable[[str], str] = lambda escaped: escaped,
    ) -> tuple[str, list[str]]:
        """The filter bar and each row's `data-facets` attribute.

        `definitions` are `(key, label)` in display order; `rows[i]` maps a key to the values row
        `i` has. A facet that fewer than two distinct values would split is left out (it filters
        nothing). `tag` marks up an escaped value (runs in other languages). Returns the bar's HTML
        (empty if there is no facet) and one attribute per row (`data-facets="..."`).
        """
        dropdowns = []
        for key, label in definitions:
            counts: dict[str, int] = {}
            for row in rows:
                for value in dict.fromkeys(row.get(key, [])):
                    counts[value] = counts.get(value, 0) + 1
            if len(counts) < 2:
                continue
            options = "".join(
                f'<label><input type="checkbox" data-facet="{html.escape(key)}" '
                f'value="{html.escape(value)}"><span class="v">{tag(html.escape(value))}'
                f'</span><span class="count">{count}</span></label>'
                for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            )
            dropdowns.append(
                f'<details class="facet"><summary>{html.escape(label)}<span class="n"></span>'
                f'</summary><div class="menu">{options}</div></details>'
            )
        attrs = [
            f'data-facets="{html.escape(json.dumps(row, ensure_ascii=False), quote=True)}"'
            for row in rows
        ]
        if not dropdowns:
            return "", attrs
        bar = (
            '<div class="filters" aria-label="Filters">'
            + "".join(dropdowns)
            + '<button type="button" data-clear hidden>Clear filters</button>'
            + '<span class="facet-status" aria-live="polite"></span></div>'
        )
        return bar, attrs
