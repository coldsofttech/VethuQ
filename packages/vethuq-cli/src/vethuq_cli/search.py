"""`vethuq search <content>` command for searching indexed OCR content."""

from __future__ import annotations

import shutil
import sys
import textwrap

import typer
from vethuq_core.db import connect
from vethuq_core.search import SearchMatch, search_indexed_content
from vethuq_core.settings import get_search_snippet_context_chars

_MIN_BOX_WIDTH = 20
_HEADER_COLOR = typer.colors.BRIGHT_WHITE
_ACCENT_COLORS = [typer.colors.BRIGHT_CYAN, typer.colors.BRIGHT_MAGENTA]
_MORE_PROMPT_COLOR = typer.colors.BRIGHT_GREEN
_CLEAR_LINE = "\r\x1b[2K"


def _read_key_windows() -> str:
    import msvcrt

    while True:
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):  # extended-key prefix (arrows, page up/down, ...)
            ch2 = msvcrt.getch()
            if ch2 == b"P":  # down arrow
                return "down"
            if ch2 in (b"Q", b"O"):  # page down / end
                return "page"
            continue
        if ch in (b"q", b"Q", b"\x1b"):
            return "quit"
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
    old_settings = termios.tcgetattr(fd)  # type: ignore[attr-defined]
    try:
        tty.setcbreak(fd)  # type: ignore[attr-defined]  # keeps Ctrl+C as SIGINT, unlike raw mode
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
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == " ":
                return "page"
            if ch in ("\r", "\n"):
                return "down"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore[attr-defined]


def _page(rendered: str) -> None:
    """Show `rendered` a screen at a time with no external pager process.

    The down arrow (or Enter) reveals one more line, space/page-down reveals
    a screenful, and `q` closes the results immediately - exactly like
    Ctrl+C, since Click already handles a `KeyboardInterrupt` that way.
    Falls back to printing everything at once when stdout isn't an
    interactive terminal (piped output, or under test).
    """
    lines = rendered.split("\n")
    if not sys.stdout.isatty():
        for line in lines:
            typer.echo(line)
        return

    read_key = _read_key_windows if sys.platform == "win32" else _read_key_posix
    total = len(lines)
    height = max(shutil.get_terminal_size().lines - 1, 1)
    top = min(height, total)
    for line in lines[:top]:
        typer.echo(line)

    while top < total:
        typer.echo(
            typer.style("-- more (q to quit) --", fg=_MORE_PROMPT_COLOR, bold=True), nl=False
        )
        key = read_key()
        typer.echo(_CLEAR_LINE, nl=False)
        if key == "quit":
            raise KeyboardInterrupt
        step = height if key == "page" else 1 if key == "down" else 0
        next_top = min(top + step, total)
        for line in lines[top:next_top]:
            typer.echo(line)
        top = next_top
        height = max(shutil.get_terminal_size().lines - 1, 1)


def search(
    content: str = typer.Argument(..., help="Text to search for in indexed content."),
) -> None:
    """Search indexed content for CONTENT and print matching pages.

    Only successfully indexed documents are searched. Results open in a
    pager at the top - scroll (e.g. the down arrow) to reveal more, `q` to
    close. A file with several matching pages prints its `File:` line once,
    followed by one `Page: X of Y` and boxed, highlighted snippet per match;
    consecutive files alternate accent colors to make them easier to tell
    apart. How much context the box shows is configurable via
    `vethuq settings snippet`.
    """
    conn = connect()
    try:
        matches = search_indexed_content(conn, content)
        if not matches:
            typer.secho("No matches found.", fg=typer.colors.YELLOW)
            return

        width = max(get_search_snippet_context_chars(conn), _MIN_BOX_WIDTH)

        match_word = "match" if len(matches) == 1 else "matches"
        lines = [
            typer.style(f"Results: {len(matches)} {match_word}", fg=_HEADER_COLOR, bold=True),
            "",
        ]
        last_file_path: str | None = None
        file_index = -1
        accent = _ACCENT_COLORS[0]
        for match in matches:
            if match.file_path != last_file_path:
                last_file_path = match.file_path
                file_index += 1
                accent = _ACCENT_COLORS[file_index % len(_ACCENT_COLORS)]
                lines.append(typer.style(f"File: {match.file_path}", fg=accent, bold=True))
            if match.page_number is not None:
                lines.append(
                    typer.style(f"Page: {match.page_number} of {match.total_pages}", fg=accent)
                )
            lines.append("")
            lines.extend(_render_box(match, width, accent))
            lines.append("")
        _page("\n".join(lines))
    finally:
        conn.close()


def _render_box(match: SearchMatch, width: int, accent: str) -> list[str]:
    prefix = "..." if match.truncated_before else ""
    suffix = "..." if match.truncated_after else ""
    full_text = f"{prefix}{match.before}{match.matched}{match.after}{suffix}"
    match_start = len(prefix) + len(match.before)
    match_end = match_start + len(match.matched)

    interior_width = width + 4
    border = typer.style("|", fg=accent)
    box = [
        typer.style("_" * interior_width, fg=accent),
        f"{border}{' ' * interior_width}{border}",
    ]
    for line, start in _wrap_with_offsets(full_text, width):
        padded = line.ljust(width)
        local_start = max(0, match_start - start)
        local_end = min(len(padded), match_end - start)
        if 0 <= local_start < local_end:
            styled = (
                padded[:local_start]
                + typer.style(
                    padded[local_start:local_end],
                    fg=typer.colors.BLACK,
                    bg=typer.colors.BRIGHT_YELLOW,
                    bold=True,
                )
                + padded[local_end:]
            )
        else:
            styled = padded
        box.append(f"{border}   {styled} {border}")
    box.append(f"{border}{typer.style('_' * interior_width, fg=accent)}{border}")
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
