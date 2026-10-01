"""`vethuq search <content>` command for searching indexed OCR content."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.prompt import Prompt
from rich.text import Text
from vethuq_core.db import Db
from vethuq_core.search import Export, Search
from vethuq_core.settings import InvalidSettingValueError, SearchSettings

from vethuq_cli.console import console, error_console
from vethuq_cli.search.pager import Pager
from vethuq_cli.search.renderer import ResultRenderer
from vethuq_cli.theme import Theme


def search(
    content: str = typer.Argument(..., help="Text to search for in indexed content."),
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

    Only successfully indexed documents are searched. Results open in a
    pager at the top - scroll (e.g. the down arrow) to reveal more, `e` to
    export what's been found and close the pager, `q` to close without
    exporting. A file with several matching pages prints its `File:` line once,
    followed by one `Page: X of Y` and boxed, highlighted snippet per match;
    consecutive files alternate accent colors to make them easier to tell
    apart. How much context the box shows is configurable via
    `vethuq settings search snippet`.

    With `--export`, results are written to that file as JSON or HTML
    instead of being printed here.
    """
    conn = Db.connect()
    try:
        matches = Search.indexed_content(conn, content)
        if not matches:
            console.print("No matches found.", style=Theme.NOTICE)
            return

        if export is not None:
            try:
                resolved_format = SearchSettings.resolve_export_format(conn, format_)
            except InvalidSettingValueError as exc:
                error_console.print(f"Error: {exc}", style=Theme.ERROR)
                raise typer.Exit(code=1) from exc
            output_path = Path(export)
            Export.search_results(matches, content, output_path, resolved_format)
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
                default=SearchSettings.get_export_format(conn),
                choices=list(SearchSettings.EXPORT_FORMATS),
            ).strip()
            output_path = Path(output)
            Export.search_results(matches, content, output_path, resolved_format)
            console.print(
                Text.assemble(
                    "Exported ",
                    (str(len(matches)), Theme.VALUE),
                    f" match(es) to {output_path} ({resolved_format}).",
                )
            )

        width = max(SearchSettings.get_snippet_context_chars(conn), ResultRenderer.MIN_BOX_WIDTH)
        match_word = "match" if len(matches) == 1 else "matches"

        with console.capture() as capture:
            console.print(
                Text(f"Results: {len(matches)} {match_word}", style=ResultRenderer.HEADER_STYLE)
            )
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
                    file_line = f"File: {match.file_path}"
                    if match.duplicate_of_path is not None:
                        file_line += f"  (duplicate of {match.duplicate_of_path})"
                    console.print(Text(file_line, style=f"bold {accent}"))
                if match.page_number is not None:
                    console.print(
                        Text(f"Page: {match.page_number} of {match.total_pages}", style=accent)
                    )
                console.print()
                for line in ResultRenderer.render_box(match, width, accent):
                    console.print(line)
                console.print()
        Pager.page(capture.get(), _export_from_pager)
    finally:
        conn.close()
