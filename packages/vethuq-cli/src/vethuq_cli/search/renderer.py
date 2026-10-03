"""Drawing search results as nested panels with highlighted snippets."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from vethuq_core.search import SearchMatch, SearchOptions

from vethuq_cli.theme import Theme


class ResultRenderer:
    TITLE = "Search Results"
    ACCENT_STYLES = [Theme.PRIMARY, Theme.ACCENT]

    @staticmethod
    def describe(options: SearchOptions) -> str:
        """The engine and its non-default options, as shown after the results count."""
        parts = [f"engine: {options.engine}"]
        if options.case_sensitive:
            parts.append("case-sensitive")
        if options.threshold is not None:
            parts.append(f"threshold {options.threshold:.0%}")
        if options.distance is not None:
            parts.append(f"within {options.distance} words")
        return ", ".join(parts)

    @staticmethod
    def heading(count: int, options: SearchOptions) -> str:
        """`Search Results: 26 matches (engine: like)` - the main panel's title."""
        word = "match" if count == 1 else "matches"
        return f"{ResultRenderer.TITLE}: {count} {word} ({ResultRenderer.describe(options)})"

    @staticmethod
    def message_panel(message: str | Text, border_style: str) -> Panel:
        """A full-width "Search Results" panel around a short `message`."""
        text = Text(message, style="white") if isinstance(message, str) else message
        # The shared console is soft-wrapping, which would crop long lines in a panel.
        text.no_wrap = False
        text.overflow = "fold"
        return Panel(
            text,
            title=ResultRenderer.TITLE,
            title_align="left",
            border_style=border_style,
            expand=True,
        )

    @staticmethod
    def results_panel(title: str, file_panels: list[Panel]) -> Panel:
        """The main panel: one inner panel per file."""
        return Panel(
            Group(*file_panels),
            title=Text(title, style="bold"),
            title_align="left",
            border_style=Theme.PRIMARY,
            expand=True,
        )

    @staticmethod
    def file_panel(first: SearchMatch, accent: str, entries: list[RenderableType]) -> Panel:
        """A panel for one file: its name as the title, then its path and every match."""
        file_line = f"File: {first.file_path}"
        if first.duplicate_of_path is not None:
            file_line += f"  (duplicate of {first.duplicate_of_path})"
        path = Text(file_line, style=f"bold {accent}", no_wrap=False, overflow="fold")
        return Panel(
            Group(path, *entries),
            title=Text(first.file_name, style=f"bold {accent}"),
            title_align="left",
            border_style=accent,
            expand=True,
        )

    @staticmethod
    def match_label(match: SearchMatch, options: SearchOptions, accent: str) -> Text:
        """`Page: 1 of 3 [ocr]`, plus the similarity for a fuzzy match."""
        label = Text(style=accent)
        if match.page_number is not None:
            label.append(f"Page: {match.page_number} of {match.total_pages} ")
        label.append(f"[{match.source}]")
        if options.engine == "fuzzy" and match.score is not None:
            label.append(f" similarity {match.score:.0%}")
        return label

    @staticmethod
    def match_panel(match: SearchMatch, accent: str) -> Panel:
        """The snippet - context before, the match highlighted, context after - in a box."""
        prefix = "..." if match.truncated_before else ""
        suffix = "..." if match.truncated_after else ""
        snippet = Text(no_wrap=False, overflow="fold")
        snippet.append(f"{prefix}{match.before}", style="white")
        snippet.append(match.matched, style=f"bold {Theme.ON_HIGHLIGHT} on {accent}")
        snippet.append(f"{match.after}{suffix}", style="white")
        return Panel(snippet, border_style=accent, expand=True)
