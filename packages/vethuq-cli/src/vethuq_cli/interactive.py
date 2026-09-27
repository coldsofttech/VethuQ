"""Interactive Rich console shown when `vethuq` is run with no subcommand.

Every action here delegates to the same functions the Typer subcommands
(`source`, `index`, `settings`, `search`) call - this module is a thin menu
wrapper, not a second implementation.
"""

from __future__ import annotations

from collections.abc import Callable

import typer
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.text import Text
from vethuq_core.branding import APP_NAME, APP_TAGLINE
from vethuq_core.settings import SEARCH_EXPORT_FORMATS, THREAD_WORKERS_AUTO, THREAD_WORKERS_MAX

from vethuq_cli.console import console, error_console
from vethuq_cli.index import history as index_history
from vethuq_cli.index import pause as index_pause
from vethuq_cli.index import restart as index_restart
from vethuq_cli.index import resume as index_resume
from vethuq_cli.index import run as index_run
from vethuq_cli.index import status as index_status
from vethuq_cli.index import stop as index_stop
from vethuq_cli.search import search as run_search
from vethuq_cli.settings import (
    export_format_set,
    export_format_show,
    gpu_disable,
    gpu_enable,
    gpu_status,
    ocr_retry_set,
    ocr_retry_show,
    removed_retention_set,
    removed_retention_show,
    snippet_set,
    snippet_show,
    thread_workers_set,
    thread_workers_show,
)
from vethuq_cli.source import add as source_add
from vethuq_cli.source import list_ as source_list
from vethuq_cli.source import remove as source_remove


class _Quit(Exception):
    """Raised on 'q' from any screen to unwind straight out of the shell."""


def _print_banner() -> None:
    console.print(Panel(APP_TAGLINE, title=APP_NAME, style="bold cyan", expand=False))


def _print_menu(title: str, items: list[tuple[str, str]]) -> None:
    console.print(Text(title, style="bold underline"))
    for key, label in items:
        console.print(f"  {key}) {label}")


def _prompt_choice(choices: list[str]) -> str:
    while True:
        raw = Prompt.ask("Select", console=console).strip().lower()
        if raw in ("q", "quit"):
            raise _Quit
        if raw in choices:
            return raw
        console.print(
            f"Invalid selection. Choose one of: {', '.join(choices)}, or q to quit.",
            style="bold red",
        )


def _run_safely(action: Callable[..., None], **kwargs: object) -> None:
    try:
        action(**kwargs)
    except typer.Exit:
        pass
    except KeyboardInterrupt:
        console.print()
    except Exception as exc:  # keep the shell alive on unexpected errors
        error_console.print(f"Error: {exc}", style="bold red")


def _search_action() -> None:
    content = Prompt.ask("Search for", console=console).strip()
    if not content:
        console.print("Nothing to search.", style="bright_black")
        return
    _run_safely(run_search, content=content, export=None, format_=None)


def _sources_menu() -> None:
    while True:
        console.print()
        _print_menu("Sources", [("1", "List"), ("2", "Add"), ("3", "Remove"), ("0", "Back")])
        choice = _prompt_choice(["1", "2", "3", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(source_list)
        elif choice == "2":
            path = Prompt.ask("File or folder to register", console=console)
            _run_safely(source_add, path=path)
        elif choice == "3":
            path_or_id = Prompt.ask("Source id or path to remove", console=console)
            _run_safely(source_remove, path_or_id=path_or_id, force=False)


def _index_menu() -> None:
    while True:
        console.print()
        _print_menu(
            "Index",
            [
                ("1", "Run"),
                ("2", "Restart"),
                ("3", "Status"),
                ("4", "Stop"),
                ("5", "Pause"),
                ("6", "Resume"),
                ("7", "History"),
                ("0", "Back"),
            ],
        )
        choice = _prompt_choice(["1", "2", "3", "4", "5", "6", "7", "0"])
        if choice == "0":
            return
        if choice == "1":
            target = Prompt.ask(
                "Source id or path (blank for all pending sources)", console=console, default=""
            ).strip()
            wait = Confirm.ask("Wait for the run to finish?", console=console, default=False)
            _run_safely(index_run, target=target or None, wait=wait, force=False)
        elif choice == "2":
            target = Prompt.ask(
                "Source id or path (blank to retry every failed file)",
                console=console,
                default="",
            ).strip()
            wait = Confirm.ask("Wait for the run to finish?", console=console, default=False)
            _run_safely(index_restart, target=target or None, wait=wait, force=False)
        elif choice == "3":
            target = Prompt.ask(
                "Source id or path (blank for overall status)", console=console, default=""
            ).strip()
            _run_safely(index_status, target=target or None, as_json=False)
        elif choice == "4":
            _run_safely(index_stop, force=False)
        elif choice == "5":
            _run_safely(index_pause, force=False)
        elif choice == "6":
            _run_safely(index_resume)
        elif choice == "7":
            target = Prompt.ask(
                "Source id or path (blank for all sources)", console=console, default=""
            ).strip()
            _run_safely(index_history, target=target or None, limit=10, as_json=False)


def _settings_gpu_menu() -> None:
    while True:
        console.print()
        _print_menu(
            "Settings > GPU", [("1", "Enable"), ("2", "Disable"), ("3", "Status"), ("0", "Back")]
        )
        choice = _prompt_choice(["1", "2", "3", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(gpu_enable)
        elif choice == "2":
            _run_safely(gpu_disable)
        elif choice == "3":
            _run_safely(gpu_status)


def _settings_snippet_menu() -> None:
    while True:
        console.print()
        _print_menu("Settings > Search > Snippet", [("1", "Show"), ("2", "Set"), ("0", "Back")])
        choice = _prompt_choice(["1", "2", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(snippet_show)
        elif choice == "2":
            chars = IntPrompt.ask("Characters of context on each side of a match", console=console)
            _run_safely(snippet_set, chars=chars)


def _settings_export_format_menu() -> None:
    while True:
        console.print()
        _print_menu(
            "Settings > Search > Export Format", [("1", "Show"), ("2", "Set"), ("0", "Back")]
        )
        choice = _prompt_choice(["1", "2", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(export_format_show)
        elif choice == "2":
            format_ = Prompt.ask("Format", console=console, choices=list(SEARCH_EXPORT_FORMATS))
            _run_safely(export_format_set, format_=format_)


def _settings_search_menu() -> None:
    while True:
        console.print()
        _print_menu("Settings > Search", [("1", "Snippet"), ("2", "Export Format"), ("0", "Back")])
        choice = _prompt_choice(["1", "2", "0"])
        if choice == "0":
            return
        if choice == "1":
            _settings_snippet_menu()
        elif choice == "2":
            _settings_export_format_menu()


def _settings_removed_retention_menu() -> None:
    while True:
        console.print()
        _print_menu(
            "Settings > Index > Removed Retention", [("1", "Show"), ("2", "Set"), ("0", "Back")]
        )
        choice = _prompt_choice(["1", "2", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(removed_retention_show)
        elif choice == "2":
            minutes = IntPrompt.ask(
                "Minutes to keep a removed source before it's purged", console=console
            )
            _run_safely(removed_retention_set, minutes=minutes)


def _settings_ocr_retry_menu() -> None:
    while True:
        console.print()
        _print_menu("Settings > Index > OCR Retry", [("1", "Show"), ("2", "Set"), ("0", "Back")])
        choice = _prompt_choice(["1", "2", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(ocr_retry_show)
        elif choice == "2":
            attempts = IntPrompt.ask(
                "Times to retry a file's OCR after a transient failure", console=console
            )
            _run_safely(ocr_retry_set, attempts=attempts)


def _settings_thread_workers_menu() -> None:
    while True:
        console.print()
        _print_menu(
            "Settings > Index > Thread Workers", [("1", "Show"), ("2", "Set"), ("0", "Back")]
        )
        choice = _prompt_choice(["1", "2", "0"])
        if choice == "0":
            return
        if choice == "1":
            _run_safely(thread_workers_show)
        elif choice == "2":
            choices = [str(n) for n in range(THREAD_WORKERS_MAX + 1)] + [THREAD_WORKERS_AUTO]
            value = Prompt.ask(
                f"0 (disable), 1-{THREAD_WORKERS_MAX}, or '{THREAD_WORKERS_AUTO}'",
                console=console,
                choices=choices,
            )
            _run_safely(thread_workers_set, value=value)


def _settings_index_menu() -> None:
    while True:
        console.print()
        _print_menu(
            "Settings > Index",
            [
                ("1", "Removed Retention"),
                ("2", "OCR Retry"),
                ("3", "Thread Workers"),
                ("0", "Back"),
            ],
        )
        choice = _prompt_choice(["1", "2", "3", "0"])
        if choice == "0":
            return
        if choice == "1":
            _settings_removed_retention_menu()
        elif choice == "2":
            _settings_ocr_retry_menu()
        elif choice == "3":
            _settings_thread_workers_menu()


def _settings_menu() -> None:
    while True:
        console.print()
        _print_menu("Settings", [("1", "GPU"), ("2", "Search"), ("3", "Index"), ("0", "Back")])
        choice = _prompt_choice(["1", "2", "3", "0"])
        if choice == "0":
            return
        if choice == "1":
            _settings_gpu_menu()
        elif choice == "2":
            _settings_search_menu()
        elif choice == "3":
            _settings_index_menu()


def run_interactive() -> None:
    """Show the interactive shell used when `vethuq` is invoked with no subcommand."""
    _print_banner()
    try:
        while True:
            console.print()
            _print_menu(
                "Main Menu",
                [
                    ("1", "Search"),
                    ("2", "Sources"),
                    ("3", "Index"),
                    ("4", "Settings"),
                    ("5", "Exit"),
                ],
            )
            choice = _prompt_choice(["1", "2", "3", "4", "5"])
            if choice == "5":
                break
            if choice == "1":
                _search_action()
            elif choice == "2":
                _sources_menu()
            elif choice == "3":
                _index_menu()
            elif choice == "4":
                _settings_menu()
    except _Quit:
        pass
    console.print()
    console.print("Goodbye.", style="bright_black")
