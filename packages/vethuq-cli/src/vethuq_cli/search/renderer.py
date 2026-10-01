"""Drawing search results as boxed, highlighted snippets."""

from __future__ import annotations

import textwrap

from rich.text import Text
from vethuq_core.search import SearchMatch

from vethuq_cli.theme import Theme


class ResultRenderer:
    MIN_BOX_WIDTH = 20
    HEADER_STYLE = "bold bright_white"
    ACCENT_STYLES = [Theme.PRIMARY, Theme.ACCENT]

    @staticmethod
    def render_box(match: SearchMatch, width: int, accent: str) -> list[Text]:
        prefix = "..." if match.truncated_before else ""
        suffix = "..." if match.truncated_after else ""
        full_text = f"{prefix}{match.before}{match.matched}{match.after}{suffix}"
        match_start = len(prefix) + len(match.before)
        match_end = match_start + len(match.matched)

        interior_width = width + 4
        border: tuple[str, str] = ("|", accent)
        box = [
            Text("_" * interior_width, style=accent),
            Text.assemble(border, " " * interior_width, border),
        ]
        for line, start in ResultRenderer.wrap_with_offsets(full_text, width):
            padded = line.ljust(width)
            local_start = max(0, match_start - start)
            local_end = min(len(padded), match_end - start)
            body = Text(padded)
            if 0 <= local_start < local_end:
                body.stylize(f"bold {Theme.ON_HIGHLIGHT} on {accent}", local_start, local_end)
            box.append(Text.assemble(border, "   ", body, " ", border))
        box.append(Text.assemble(border, ("_" * interior_width, accent), border))
        return box

    @staticmethod
    def wrap_with_offsets(text: str, width: int) -> list[tuple[str, int]]:
        """Word-wrap `text` to `width`, pairing each line with its start offset in `text`."""
        wrapped = textwrap.wrap(text, width=width) or [""]
        lines = []
        cursor = 0
        for line in wrapped:
            start = text.index(line, cursor)
            lines.append((line, start))
            cursor = start + len(line)
        return lines
