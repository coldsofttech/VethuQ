"""Drawing search results as nested panels with highlighted snippets."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.search import PageResult, SearchMatch, SearchOptions
from vethuq_core.search.engines import Ranking

from vethuq_cli.theme import Theme


class ResultRenderer:
    TITLE = "Search Results"
    ACCENT_STYLES = [Theme.PRIMARY, Theme.ACCENT]
    HITS_PER_PAGE = 3  # boxes shown per page in the combined search; the rest are counted

    @staticmethod
    def describe(options: SearchOptions) -> str:
        """The engine and its non-default options, as shown after the results count."""
        parts = [f"engine: {options.engine}"]
        if options.case_sensitive:
            parts.append("case-sensitive")
        if options.engine == "fuzzy" and options.threshold is not None:
            parts.append(f"threshold {options.threshold:.0%}")
        if options.engine == "proximity" and options.distance is not None:
            parts.append(f"within {options.distance} words")
        return ", ".join(parts)

    @staticmethod
    def heading(count: int, options: SearchOptions) -> str:
        """`Search Results: 26 matches (engine: like)` - the main panel's title."""
        word = "match" if count == 1 else "matches"
        return f"{ResultRenderer.TITLE}: {count} {word} ({ResultRenderer.describe(options)})"

    @staticmethod
    def page_heading(count: int, options: SearchOptions) -> str:
        """`Search Results: 4 pages (engine: all)` - the main panel's title for ranked pages."""
        word = "page" if count == 1 else "pages"
        return f"{ResultRenderer.TITLE}: {count} {word} ({ResultRenderer.describe(options)})"

    @staticmethod
    def legend() -> Group:
        """What each match label means, strictest first - the results pager's `h` footer."""
        table = Table.grid(padding=(0, 2))
        table.add_column(style=f"bold {Theme.PRIMARY}", no_wrap=True)
        table.add_column(style="bright_black")
        for engine in Ranking.TIERS:
            table.add_row(f"[{Ranking.BADGES[engine]}]", Ranking.MEANINGS[engine])
        footer = Text(
            "Ranked strictest first; a page's label is its strictest match and `also:` "
            "lists the other ways it was found.",
            style="bright_black",
            no_wrap=False,
            overflow="fold",
        )
        return Group(table, footer)

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
    def file_panel(
        first: SearchMatch | PageResult, accent: str, entries: list[RenderableType]
    ) -> Panel:
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
    def match_entries(
        match: SearchMatch, options: SearchOptions, accent: str
    ) -> list[RenderableType]:
        """A match's label and snippet box."""
        return [
            ResultRenderer.match_label(match, options, accent),
            ResultRenderer.match_panel(match, accent),
        ]

    @staticmethod
    def page_label(page: PageResult, accent: str) -> Text:
        """`Page: 1 of 3 [ocr] [Exact]  also: Contains, Word` - how a ranked page was found."""
        label = Text(style=accent)
        if page.page_number is not None:
            label.append(f"Page: {page.page_number} of {page.total_pages} ")
        label.append(f"[{page.source}] ")
        label.append(f"[{Ranking.hit_badge(page.hits[0])}]", style=f"bold {accent}")
        also = sorted(set(page.matched_by) - {page.engine}, key=Ranking.engine_rank)
        if also:
            label.append("  also: " + ", ".join(Ranking.BADGES[e] for e in also), style="dim")
        return label

    @staticmethod
    def page_entries(page: PageResult, accent: str) -> list[RenderableType]:
        """A ranked page's label, then its best few hits (each tagged with how it was found)."""
        entries: list[RenderableType] = [ResultRenderer.page_label(page, accent)]
        for number, hit in enumerate(page.hits[: ResultRenderer.HITS_PER_PAGE]):
            if number:  # the first hit is what the page's own label already says
                entries.append(Text(f"[{Ranking.hit_badge(hit)}]", style=accent))
            entries.append(ResultRenderer.match_panel(hit, accent))
        hidden = len(page.hits) - ResultRenderer.HITS_PER_PAGE
        if hidden > 0:
            word = "match" if hidden == 1 else "matches"
            entries.append(Text(f"+{hidden} more {word} on this page", style="bright_black"))
        return entries

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
