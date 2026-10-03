"""A minimal pager: shows output a screen at a time with no external process."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable

from rich.text import Text

from vethuq_cli.console import console
from vethuq_cli.theme import Theme


class Pager:
    MORE_PROMPT = "-- More (Enter key for new line; e to export; q for quit)  --"
    MORE_PROMPT_WITH_HELP = (
        "-- More (Enter key for new line; e to export; h for help; q for quit)  --"
    )
    MORE_PROMPT_HIDE_HELP = (
        "-- More (Enter key for new line; e to export; h to hide help; q for quit)  --"
    )
    MORE_PROMPT_STYLE = Theme.OK
    CLEAR_LINE = "\r\x1b[2K"
    CLEAR_FROM_LINE = "\r\x1b[J"  # this line and everything below it
    CURSOR_UP = "\x1b[{}A"

    @staticmethod
    def read_key_windows() -> str:
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
            if ch in (b"h", b"H"):
                return "help"
            if ch == b"\x03":  # Ctrl+C
                raise KeyboardInterrupt
            if ch == b" ":
                return "page"
            if ch in (b"\r", b"\n"):
                return "down"

    @staticmethod
    def read_key_posix() -> str:
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
                if ch in ("h", "H"):
                    return "help"
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch == " ":
                    return "page"
                if ch in ("\r", "\n"):
                    return "down"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    @staticmethod
    def write_line(line: str) -> None:
        sys.stdout.write(line + "\n")

    @staticmethod
    def render_prompt(with_help: bool = False, help_open: bool = False) -> str:
        text = Pager.MORE_PROMPT_WITH_HELP if with_help else Pager.MORE_PROMPT
        if with_help and help_open:
            text = Pager.MORE_PROMPT_HIDE_HELP
        with console.capture() as capture:
            console.print(Text(text, style=Pager.MORE_PROMPT_STYLE), end="")
        return capture.get()

    @staticmethod
    def page(rendered: str, on_export: Callable[[], None], help_text: str | None = None) -> None:
        """Show `rendered` a screen at a time with no external pager process.

        The down arrow (or Enter) reveals one more line, space/page-down reveals
        a screenful, `e` exports the results (via `on_export`) and closes the
        pager, and `q` closes the results immediately - exactly like Ctrl+C,
        since Click already handles a `KeyboardInterrupt` that way. Falls back
        to printing everything at once when stdout isn't an interactive
        terminal (piped output, or under test) - `e` isn't available there.
        When `help_text` (already rendered, like `rendered`) is given, `h` toggles
        it open and shut as a footer under the prompt - redrawn in place, so
        nothing lands in the middle of the results - and the prompt mentions `h`.
        `rendered` is expected to already carry any ANSI styling (e.g. from
        `console.capture()`), which is written straight through rather than
        re-parsed by Rich.
        """
        lines = rendered.split("\n")
        if not sys.stdout.isatty():
            for line in lines:
                Pager.write_line(line)
            return

        read_key = Pager.read_key_windows if sys.platform == "win32" else Pager.read_key_posix
        total = len(lines)
        height = max(shutil.get_terminal_size().lines - 1, 1)
        top = min(height, total)
        for line in lines[:top]:
            Pager.write_line(line)

        help_lines = help_text.rstrip("\n").split("\n") if help_text is not None else []
        help_open = False
        while top < total:
            sys.stdout.write(Pager.render_prompt(help_text is not None, help_open))
            if help_open:
                sys.stdout.write("\n" + "\n".join(help_lines))
            sys.stdout.flush()
            key = read_key()
            if help_open:  # back up to the prompt line; the clear below wipes the footer too
                sys.stdout.write(Pager.CURSOR_UP.format(len(help_lines)))
            sys.stdout.write(Pager.CLEAR_FROM_LINE)
            if key == "quit":
                raise KeyboardInterrupt
            if key == "export":
                on_export()
                return
            if key == "help":
                if help_text is not None:
                    help_open = not help_open
                continue
            step = height if key == "page" else 1 if key == "down" else 0
            next_top = min(top + step, total)
            for line in lines[top:next_top]:
                Pager.write_line(line)
            top = next_top
            height = max(shutil.get_terminal_size().lines - 1, 1)
