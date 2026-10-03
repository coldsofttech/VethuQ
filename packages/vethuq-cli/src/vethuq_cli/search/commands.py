"""`vethuq search <content>` command for searching indexed OCR content."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from vethuq_core.search import (
    Export,
    PageResult,
    Search,
    SearchMatch,
    SearchOptionError,
    SearchOptions,
    SearchQueryError,
)
from vethuq_core.search.engines import Ranking
from vethuq_core.settings import InvalidSettingValueError, SearchSettings
from vethuq_core.storage import Storage, open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.search.pager import Pager
from vethuq_cli.search.renderer import ResultRenderer
from vethuq_cli.theme import Theme

_NO_MATCH_HINTS = {
    "exact": "`exact` only finds the text as typed, as a whole word. "
    "Try `--engine like` to match part of a word or ignore case.",
    "full-text": "`full-text` only finds whole words (add `*` for a prefix, e.g. `mus*`). "
    "Try `--engine like` to match part of a word.",
    "fuzzy": "`fuzzy` only finds whole words close to yours (words under 4 letters and "
    "numbers must match exactly). Try `--fuzziness loose` or `--engine like`.",
    "proximity": "`proximity` needs every word within the distance of the others, as whole "
    "words. Try `--distance loose` or `--engine full-text`.",
}


def _resolve_options(
    storage: Storage,
    engine: str | None,
    case_sensitive: bool | None,
    threshold: str | None,
    fuzziness: str | None,
    distance: str | None,
) -> SearchOptions:
    """`Search.resolve_options`, with an unusable combination reported as a usage error.

    `fuzziness` is the preset-name form of `threshold`; giving both is an error.
    """
    if fuzziness is not None:
        if threshold is not None:
            raise typer.BadParameter(
                "give either --threshold or --fuzziness, not both.", param_hint="--fuzziness"
            )
        preset = SearchSettings.FUZZY_PRESETS.get(fuzziness.strip().lower())
        if preset is None:
            raise typer.BadParameter(
                f"{fuzziness!r} is not one of {', '.join(SearchSettings.FUZZY_PRESETS)}.",
                param_hint="--fuzziness",
            )
        threshold = str(preset)
    try:
        return Search.resolve_options(storage, engine, case_sensitive, threshold, distance)
    except SearchOptionError as exc:
        if exc.option == "engine":
            hint = "--engine"
        elif exc.option == "threshold":
            hint = "--fuzziness" if fuzziness is not None else "--threshold"
        elif exc.option == "distance":
            hint = "--distance"
        else:
            hint = "--case-sensitive" if case_sensitive else "--no-case-sensitive"
        raise typer.BadParameter(str(exc), param_hint=hint) from exc


class SearchHelp:
    TEXT = (
        "Search indexed content for CONTENT and print matching pages. Only successfully "
        "indexed documents are searched.\n\n"
        "--engine picks how CONTENT is matched:\n\n"
        "all (the default) - runs every engine and lists each page once, ranked by the "
        "strictest way it matched: Exact, Contains, Relevant, Near, Word, then Similar. Each "
        "page is labelled with that, the other engines that found it, and any hit found less "
        "strictly than the page's best. Each engine applies the options it can.\n\n"
        "like - finds CONTENT anywhere, even inside a word, ignoring case. "
        '`mus` finds "Museum". Results are ordered by file path.\n\n'
        "lexical - finds CONTENT anywhere, even inside a word, like `like`, but lists the "
        "best-matching pages first. Needs at least 3 characters.\n\n"
        "exact - finds CONTENT exactly as typed: same case, as a whole word. `Museum` finds "
        '"Museum" but not "museum" or "Museums". Always case-sensitive.\n\n'
        "full-text - finds pages containing all your words, in any order, ignoring case and "
        'matching English word forms such as plurals (`museum` finds "Museums"). Quote a '
        '"phrase" to keep words together, and end a word with * for a prefix (`mus*`). Best '
        "matches first. Never case-sensitive.\n\n"
        "fuzzy - finds words close to yours, tolerating typos and OCR misreads (`Musuem` or "
        "`Museurn` for `Museum`). Every word must be matched, as close as --threshold or "
        "--fuzziness allows; words under 4 letters and anything with a digit must match "
        "exactly. Closest matches first.\n\n"
        "proximity - finds passages where all your words (at least two, any order; quote a "
        '"phrase" to keep words together) sit within --distance words of each other, such '
        "as `payment` and `termination` in the same clause. One result per passage, best "
        "pages first. Never case-sensitive.\n\n"
        "Results open in a pager at the top: scroll (e.g. the down arrow) to reveal more, "
        "`e` to export what's been found and close the pager, `h` (with the default `all` "
        "engine) to see what Exact, Contains, Relevant, Near, Word and Similar mean, `q` to close "
        "without exporting. A file with several matching pages prints its file name as a bold "
        "heading and its `File:` path line once, followed by one `Page: X of Y` and a "
        "boxed, highlighted snippet per match; consecutive files alternate accent colors. "
        "How much context the box shows is set by `vethuq settings search snippet`.\n\n"
        "With --export, results are written to that file as JSON or HTML instead of being "
        "printed here."
    )


def search(
    content: str = typer.Argument(..., help="Text to search for in indexed content."),
    engine: str | None = typer.Option(
        None,
        "--engine",
        help=(
            "How to match: 'all' (every engine at once, the pages ranked together - the "
            "default), 'like' (substring, even inside a word), 'exact' (as typed, "
            "case-sensitive, whole word), 'full-text' (whole words, stemmed, best match "
            "first), 'fuzzy' (whole words close to yours, tolerating typos and OCR "
            "misreads) or 'proximity' (all your words near each other). Defaults to "
            "`vethuq settings search engine`."
        ),
    ),
    case_sensitive: bool | None = typer.Option(
        None,
        "--case-sensitive/--no-case-sensitive",
        help=(
            "Match case. Only 'like', 'lexical' and 'fuzzy' honour it (default: `vethuq settings "
            "search case-sensitive`); 'exact' is always case-sensitive, 'full-text' and "
            "'proximity' never are. With 'all', each engine applies what it can."
        ),
    ),
    threshold: str | None = typer.Option(
        None,
        "--threshold",
        help=(
            "Fuzzy only: the minimum similarity between your words and the words found, as a "
            "percentage (80%) or a number above 0 and up to 1 (0.8). Default: `vethuq settings "
            "search fuzzy threshold`."
        ),
    ),
    fuzziness: str | None = typer.Option(
        None,
        "--fuzziness",
        help=(
            "Fuzzy only: a named --threshold - 'strict' (0.90), 'balanced' (0.80) or "
            "'loose' (0.65)."
        ),
    ),
    distance: str | None = typer.Option(
        None,
        "--distance",
        help=(
            "Proximity only: the most words between your first and last word - a number from "
            "1 to 100, or 'tight' (3), 'medium' (10) or 'loose' (30). Default: `vethuq "
            "settings search proximity distance`."
        ),
    ),
    export: str | None = typer.Option(
        None,
        "--export",
        help=(
            "Also export results to this file, instead of printing them here. The format "
            "defaults to `vethuq settings search export-format` unless --format overrides it."
        ),
    ),
    format_: str | None = typer.Option(
        None,
        "--format",
        help="Export format: 'json' or 'html'. Only used with --export.",
    ),
) -> None:
    """Search indexed content for CONTENT and print matching pages."""
    storage = open_storage()
    try:
        options = _resolve_options(storage, engine, case_sensitive, threshold, fuzziness, distance)
        pages: list[PageResult] | None = None
        try:
            if options.engine == SearchSettings.ENGINE_ALL:
                pages = Search.indexed_pages(
                    storage,
                    content,
                    case_sensitive=options.case_sensitive,
                    threshold=options.threshold,
                    distance=options.distance,
                )
                matches = Ranking.flatten(pages)
            else:
                matches = Search.indexed_content(
                    storage,
                    content,
                    engine=options.engine,
                    case_sensitive=options.case_sensitive,
                    threshold=options.threshold,
                    distance=options.distance,
                )
        except SearchQueryError as exc:
            raise typer.BadParameter(str(exc), param_hint="CONTENT") from exc
        if not matches:
            message = Text("No matches found.", style=Theme.NOTICE)
            if options.engine in _NO_MATCH_HINTS:
                message.append(f"\n\n{_NO_MATCH_HINTS[options.engine]}", style="bright_black")
            console.print(ResultRenderer.message_panel(message, Theme.NOTICE))
            return

        if export is not None:
            try:
                resolved_format = SearchSettings.resolve_export_format(storage, format_)
            except InvalidSettingValueError as exc:
                error_console.print(f"Error: {exc}", style=Theme.ERROR)
                raise typer.Exit(code=1) from exc
            output_path = Path(export)
            Export.search_results(
                matches,
                content,
                output_path,
                resolved_format,
                engine=options.engine,
                case_sensitive=options.case_sensitive,
                threshold=options.threshold,
                distance=options.distance,
            )
            console.print(
                ResultRenderer.message_panel(
                    Text.assemble(
                        ("Exported ", "white"),
                        (str(len(matches)), Theme.VALUE),
                        (f" match(es) to {output_path} ({resolved_format}).", "white"),
                    ),
                    Theme.OK,
                )
            )
            return

        def _export_from_pager() -> None:
            output = Prompt.ask("Export to file", console=console).strip()
            if not output:
                console.print("Export cancelled.", style="bright_black")
                return
            resolved_format = Prompt.ask(
                "Export format",
                console=console,
                default=SearchSettings.get_export_format(storage),
                choices=list(SearchSettings.EXPORT_FORMATS),
            ).strip()
            output_path = Path(output)
            Export.search_results(
                matches,
                content,
                output_path,
                resolved_format,
                engine=options.engine,
                case_sensitive=options.case_sensitive,
                threshold=options.threshold,
                distance=options.distance,
            )
            console.print(
                ResultRenderer.message_panel(
                    Text.assemble(
                        ("Exported ", "white"),
                        (str(len(matches)), Theme.VALUE),
                        (f" match(es) to {output_path} ({resolved_format}).", "white"),
                    ),
                    Theme.OK,
                )
            )

        items: list[SearchMatch] | list[PageResult]
        if pages is not None:
            items, title = pages, ResultRenderer.page_heading(len(pages), options)
        else:
            items, title = matches, ResultRenderer.heading(len(matches), options)

        def entries_for(item: SearchMatch | PageResult, accent: str) -> list[RenderableType]:
            if isinstance(item, PageResult):
                return ResultRenderer.page_entries(item, accent)
            return ResultRenderer.match_entries(item, options, accent)

        file_panels: list[Panel] = []
        entries: list[RenderableType] = []
        first: SearchMatch | PageResult | None = None
        last_file_path: str | None = None
        accent = ResultRenderer.ACCENT_STYLES[0]

        def _close_file() -> None:
            if first is not None:
                file_panels.append(ResultRenderer.file_panel(first, accent, entries))

        for item in items:
            if item.file_path != last_file_path:
                _close_file()
                accent = ResultRenderer.ACCENT_STYLES[
                    len(file_panels) % len(ResultRenderer.ACCENT_STYLES)
                ]
                first, last_file_path, entries = item, item.file_path, []
            entries.extend(entries_for(item, accent))
        _close_file()

        with console.capture() as capture:
            console.print(ResultRenderer.results_panel(title, file_panels))
        help_text = None
        if pages is not None:  # only the combined search labels its matches
            with console.capture() as legend:
                console.print(ResultRenderer.legend())
            help_text = legend.get()
        Pager.page(capture.get(), _export_from_pager, help_text)
    finally:
        storage.close()
