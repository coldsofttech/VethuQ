"""`vethuq search <content>` command for searching indexed OCR content."""

from __future__ import annotations

import shutil
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import typer
from rich.prompt import Prompt
from rich.text import Text
from vethuq_core.db import Db
from vethuq_core.search import Export, Search, SearchMatch
from vethuq_core.settings import (
    SEARCH_EXPORT_FORMATS,
    get_search_export_format,
    get_search_snippet_context_chars,
)

from vethuq_cli.console import console, error_console

_MIN_BOX_WIDTH = 20
_HEADER_STYLE = "bold bright_white"
_ACCENT_STYLES = ["bright_cyan", "bright_magenta"]
_MORE_PROMPT = "-- More (Enter key for new line; e to export; q for quit)  --"
_MORE_PROMPT_STYLE = "bold green"
_CLEAR_LINE = "\r\x1b[2K"


def _read_key_windows() -> str:
    import msvcrt

    while True:
        ch = msvcrt.getch()  # type: ignore[attr-defined]
        if ch in (b"\x00", b"\xe0"):  # extended-key prefix (arrows, page up/down, ...)
            ch2 = msvcrt.getch()  # type: ignore[attr-defined]
            if ch2 == b"P":  # down arrow
                return "down"
            if ch2 in (b"Q", b"O"):  # page down / end
                return "page"
            continue
        if ch in (b"q", b"Q", b"\x1b"):
            return "quit"
        if ch in (b"e", b"E"):
            return "export"
        if ch == b"\x03":  # Ctrl+C
            raise KeyboardInterrupt
        if ch == b" ":
            return "page"
        if ch in (b"\r", b"\n"):
            return "down"


def _read_key_posix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)  # keeps Ctrl+C as SIGINT, unlike raw mode
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                rest = sys.stdin.read(1)
                if rest != "[":
                    continue
                code = sys.stdin.read(1)
                if code == "B":
                    return "down"
                if code in ("5", "6"):
                    sys.stdin.read(1)  # trailing '~' of the Page Up/Down sequence
                    return "page"
                continue
            if ch in ("q", "Q"):
                return "quit"
            if ch in ("e", "E"):
                return "export"
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == " ":
                return "page"
            if ch in ("\r", "\n"):
                return "down"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _write_line(line: str) -> None:
    sys.stdout.write(line + "\n")


def _render_prompt() -> str:
    with console.capture() as capture:
        console.print(Text(_MORE_PROMPT, style=_MORE_PROMPT_STYLE), end="")
    return capture.get()


def _page(rendered: str, on_export: Callable[[], None]) -> None:
    """Show `rendered` a screen at a time with no external pager process.

    The down arrow (or Enter) reveals one more line, space/page-down reveals
    a screenful, `e` exports the results (via `on_export`) and closes the
    pager, and `q` closes the results immediately - exactly like Ctrl+C,
    since Click already handles a `KeyboardInterrupt` that way. Falls back
    to printing everything at once when stdout isn't an interactive
    terminal (piped output, or under test) - `e` isn't available there.
    `rendered` is expected to already carry any ANSI styling (e.g. from
    `console.capture()`), which is written straight through rather than
    re-parsed by Rich.
    """
    lines = rendered.split("\n")
    if not sys.stdout.isatty():
        for line in lines:
            _write_line(line)
        return

    read_key = _read_key_windows if sys.platform == "win32" else _read_key_posix
    total = len(lines)
    height = max(shutil.get_terminal_size().lines - 1, 1)
    top = min(height, total)
    for line in lines[:top]:
        _write_line(line)

    prompt = _render_prompt()
    while top < total:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        key = read_key()
        sys.stdout.write(_CLEAR_LINE)
        if key == "quit":
            raise KeyboardInterrupt
        if key == "export":
            on_export()
            return
        step = height if key == "page" else 1 if key == "down" else 0
        next_top = min(top + step, total)
        for line in lines[top:next_top]:
            _write_line(line)
        top = next_top
        height = max(shutil.get_terminal_size().lines - 1, 1)


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
            console.print("No matches found.", style="yellow")
            return

        if export is not None:
            resolved_format = format_ if format_ is not None else get_search_export_format(conn)
            if resolved_format not in SEARCH_EXPORT_FORMATS:
                error_console.print(
                    f"Error: unsupported export format '{resolved_format}'. "
                    f"Use one of: {', '.join(SEARCH_EXPORT_FORMATS)}.",
                    style="bold red",
                )
                raise typer.Exit(code=1)
            output_path = Path(export)
            Export.search_results(matches, content, output_path, resolved_format)
            console.print(
                Text.assemble(
                    "Exported ",
                    (str(len(matches)), "bright_blue"),
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
                default=get_search_export_format(conn),
                choices=list(SEARCH_EXPORT_FORMATS),
            ).strip()
            output_path = Path(output)
            Export.search_results(matches, content, output_path, resolved_format)
            console.print(
                Text.assemble(
                    "Exported ",
                    (str(len(matches)), "bright_blue"),
                    f" match(es) to {output_path} ({resolved_format}).",
                )
            )

        width = max(get_search_snippet_context_chars(conn), _MIN_BOX_WIDTH)
        match_word = "match" if len(matches) == 1 else "matches"

        with console.capture() as capture:
            console.print(Text(f"Results: {len(matches)} {match_word}", style=_HEADER_STYLE))
            console.print()
            last_file_path: str | None = None
            file_index = -1
            accent = _ACCENT_STYLES[0]
            for match in matches:
                if match.file_path != last_file_path:
                    last_file_path = match.file_path
                    file_index += 1
                    accent = _ACCENT_STYLES[file_index % len(_ACCENT_STYLES)]
                    file_line = f"File: {match.file_path}"
                    if match.duplicate_of_path is not None:
                        file_line += f"  (duplicate of {match.duplicate_of_path})"
                    console.print(Text(file_line, style=f"bold {accent}"))
                if match.page_number is not None:
                    console.print(
                        Text(f"Page: {match.page_number} of {match.total_pages}", style=accent)
                    )
                console.print()
                for line in _render_box(match, width, accent):
                    console.print(line)
                console.print()
        _page(capture.get(), _export_from_pager)
    finally:
        conn.close()


def _render_box(match: SearchMatch, width: int, accent: str) -> list[Text]:
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
    for line, start in _wrap_with_offsets(full_text, width):
        padded = line.ljust(width)
        local_start = max(0, match_start - start)
        local_end = min(len(padded), match_end - start)
        body = Text(padded)
        if 0 <= local_start < local_end:
            body.stylize(f"bold black on {accent}", local_start, local_end)
        box.append(Text.assemble(border, "   ", body, " ", border))
    box.append(Text.assemble(border, ("_" * interior_width, accent), border))
    return box


def _wrap_with_offsets(text: str, width: int) -> list[tuple[str, int]]:
    """Word-wrap `text` to `width`, pairing each line with its start offset in `text`."""
    wrapped = textwrap.wrap(text, width=width) or [""]
    lines = []
    cursor = 0
    for line in wrapped:
        start = text.index(line, cursor)
        lines.append((line, start))
        cursor = start + len(line)
    return lines
