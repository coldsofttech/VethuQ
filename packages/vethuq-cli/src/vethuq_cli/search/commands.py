"""`vethuq search <content>` command for searching indexed OCR content."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.prompt import Prompt
from rich.text import Text
from vethuq_core.search import Export, Search, SearchOptionError, SearchOptions
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
}


def _resolve_options(
    storage: Storage,
    engine: str | None,
    case_sensitive: bool | None,
    threshold: float | None,
    fuzziness: str | None,
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
        threshold = preset
    try:
        return Search.resolve_options(storage, engine, case_sensitive, threshold)
    except SearchOptionError as exc:
        if exc.option == "engine":
            hint = "--engine"
        elif exc.option == "threshold":
            hint = "--fuzziness" if fuzziness is not None else "--threshold"
        else:
            hint = "--case-sensitive" if case_sensitive else "--no-case-sensitive"
        raise typer.BadParameter(str(exc), param_hint=hint) from exc


def search(
    content: str = typer.Argument(..., help="Text to search for in indexed content."),
    engine: str | None = typer.Option(
        None,
        "--engine",
        help=(
            "How to match: 'like' (substring, even inside a word), 'exact' (as typed, "
            "case-sensitive, whole word), 'full-text' (whole words, stemmed, best match "
            "first) or 'fuzzy' (whole words close to yours, tolerating typos and OCR "
            "misreads). Defaults to `vethuq settings search engine`."
        ),
    ),
    case_sensitive: bool | None = typer.Option(
        None,
        "--case-sensitive/--no-case-sensitive",
        help=(
            "Match case. Only 'like' and 'fuzzy' honour it (default: `vethuq settings "
            "search case-sensitive`); 'exact' is always case-sensitive and 'full-text' never is."
        ),
    ),
    threshold: float | None = typer.Option(
        None,
        "--threshold",
        help=(
            "Fuzzy only: the minimum similarity, above 0 and up to 1, between your words and "
            "the words found (default: `vethuq settings search fuzzy threshold`)."
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
    """Search indexed content for CONTENT and print matching pages.

    Only successfully indexed documents are searched. `--engine` picks how
    CONTENT is matched: `like` finds it anywhere, even inside a word, ignoring
    case; `exact` finds it as typed - same case, as a whole word; `full-text`
    finds pages containing its words (any case, English word forms such as
    plurals, quote a "phrase", end a word with * for a prefix) and lists the
    best matches first; `fuzzy` finds words close to yours - typos and OCR
    misreads such as `Musuem` or `Museurn` for `Museum` - as close as
    `--threshold`/`--fuzziness` allows (words under 4 letters and anything
    with a digit must match exactly), closest first. Results open in a
    pager at the top - scroll (e.g. the down arrow) to reveal more, `e` to
    export what's been found and close the pager, `q` to close without
    exporting. A file with several matching pages prints its file name as a
    bold heading and its `File:` path line once, followed by one `Page: X of Y`
    and boxed, highlighted snippet per match;
    consecutive files alternate accent colors to make them easier to tell
    apart. How much context the box shows is configurable via
    `vethuq settings search snippet`.

    With `--export`, results are written to that file as JSON or HTML
    instead of being printed here.
    """
    storage = open_storage()
    try:
        options = _resolve_options(storage, engine, case_sensitive, threshold, fuzziness)
        matches = Search.indexed_content(
            storage,
            content,
            engine=options.engine,
            case_sensitive=options.case_sensitive,
            threshold=options.threshold,
        )
        if not matches:
            console.print("No matches found.", style=Theme.NOTICE)
            if options.engine in _NO_MATCH_HINTS:
                console.print(_NO_MATCH_HINTS[options.engine], style="bright_black")
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
            )
            console.print(
                Text.assemble(
                    "Exported ",
                    (str(len(matches)), Theme.VALUE),
                    f" match(es) to {output_path} ({resolved_format}).",
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
            )
            console.print(
                Text.assemble(
                    "Exported ",
                    (str(len(matches)), Theme.VALUE),
                    f" match(es) to {output_path} ({resolved_format}).",
                )
            )

        width = max(SearchSettings.get_snippet_context_chars(storage), ResultRenderer.MIN_BOX_WIDTH)
        match_word = "match" if len(matches) == 1 else "matches"

        with console.capture() as capture:
            header = f"Results: {len(matches)} {match_word} ({ResultRenderer.describe(options)})"
            console.print(Text(header, style=ResultRenderer.HEADER_STYLE))
            console.print()
            last_file_path: str | None = None
            file_index = -1
            accent = ResultRenderer.ACCENT_STYLES[0]
            for match in matches:
                if match.file_path != last_file_path:
                    last_file_path = match.file_path
                    file_index += 1
                    accent = ResultRenderer.ACCENT_STYLES[
                        file_index % len(ResultRenderer.ACCENT_STYLES)
                    ]
                    console.print(Text(match.file_name, style=f"bold {accent}"))
                    file_line = f"File: {match.file_path}"
                    if match.duplicate_of_path is not None:
                        file_line += f"  (duplicate of {match.duplicate_of_path})"
                    console.print(Text(file_line, style=f"bold {accent}"))
                label = Text(style=accent)
                if match.page_number is not None:
                    label.append(f"Page: {match.page_number} of {match.total_pages} ")
                label.append(f"[{match.source}]")
                if options.engine == "fuzzy" and match.score is not None:
                    label.append(f" similarity {match.score:.0%}")
                console.print(label)
                console.print()
                for line in ResultRenderer.render_box(match, width, accent):
                    console.print(line)
                console.print()
        Pager.page(capture.get(), _export_from_pager)
    finally:
        storage.close()
