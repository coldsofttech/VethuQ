"""Interactive Rich console shown when `vethuq` is run with no subcommand.

Every action here delegates to the same functions the Typer subcommands
(`source`, `index`, `settings`, `search`) call - this module is a thin menu
wrapper, not a second implementation.
"""

from __future__ import annotations

from collections.abc import Callable

import typer
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.text import Text
from vethuq_core.branding import APP_NAME, APP_TAGLINE
from vethuq_core.settings import (
    DbSettings,
    IndexSettings,
    LogSettings,
    OcrSettings,
    SearchSettings,
)
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.db import integrity_check as db_integrity_check
from vethuq_cli.index.commands import history as index_history
from vethuq_cli.index.commands import pause as index_pause
from vethuq_cli.index.commands import restart as index_restart
from vethuq_cli.index.commands import resume as index_resume
from vethuq_cli.index.commands import run as index_run
from vethuq_cli.index.commands import status as index_status
from vethuq_cli.index.commands import stop as index_stop
from vethuq_cli.logs import LogsCommand
from vethuq_cli.search import search as run_search
from vethuq_cli.settings import (
    case_sensitive_disable,
    case_sensitive_enable,
    case_sensitive_show,
    engine_set,
    engine_show,
    export_format_set,
    export_format_show,
    fuzzy_threshold_set,
    fuzzy_threshold_show,
    gpu_disable,
    gpu_enable,
    gpu_status,
    integrity_check_interval_set,
    integrity_check_interval_show,
    integrity_check_set,
    integrity_check_show,
    log_level_set,
    log_level_show,
    log_retention_set,
    log_retention_show,
    removed_retention_set,
    removed_retention_show,
    retry_set,
    retry_show,
    search_engine_set,
    search_engine_show,
    snippet_set,
    snippet_show,
    stability_check_set,
    stability_check_show,
    stale_lock_set,
    stale_lock_show,
    thread_workers_set,
    thread_workers_show,
)
from vethuq_cli.source import add as source_add
from vethuq_cli.source import list_ as source_list
from vethuq_cli.source import remove as source_remove
from vethuq_cli.stats.commands import reset as stats_reset
from vethuq_cli.stats.commands import show as stats_show
from vethuq_cli.theme import Theme


class _Quit(Exception):
    """Raised on 'q' from any screen to unwind straight out of the shell."""


class InteractiveMenu:
    @staticmethod
    def _print_banner() -> None:
        console.print(Panel(APP_TAGLINE, title=APP_NAME, style=Theme.BRAND, expand=False))

    @staticmethod
    def _print_menu(title: str, items: list[tuple[str, str]]) -> None:
        console.print(Text(title, style="bold underline"))
        for key, label in items:
            console.print(f"  {key}) {label}")

    @staticmethod
    def _prompt_choice(choices: list[str]) -> str:
        while True:
            raw = Prompt.ask("Select", console=console).strip().lower()
            if raw in ("q", "quit"):
                raise _Quit
            if raw in choices:
                return raw
            console.print(
                f"Invalid selection. Choose one of: {', '.join(choices)}, or q to quit.",
                style=Theme.ERROR,
            )

    @staticmethod
    def _run_safely(action: Callable[..., None], **kwargs: object) -> None:
        try:
            action(**kwargs)
        except typer.Exit:
            pass
        except KeyboardInterrupt:
            console.print()
        except Exception as exc:  # keep the shell alive on unexpected errors
            error_console.print(f"Error: {exc}", style=Theme.ERROR)

    @staticmethod
    def _search_action() -> None:
        content = Prompt.ask("Search for", console=console).strip()
        if not content:
            console.print("Nothing to search.", style="bright_black")
            return
        storage = open_storage()
        try:
            default_engine = SearchSettings.get_engine(storage)
            default_case_sensitive = SearchSettings.is_case_sensitive(storage)
            default_threshold = SearchSettings.get_fuzzy_threshold_setting(storage)
        finally:
            storage.close()
        engine = Prompt.ask(
            "Engine", console=console, choices=list(SearchSettings.ENGINES), default=default_engine
        )
        # Only `like` and `fuzzy` have a choice to make: `exact` is always
        # case-sensitive and `full-text` never is, so asking would have no effect.
        case_sensitive: bool | None = None
        if engine in ("like", "fuzzy"):
            case_sensitive = Confirm.ask(
                "Case-sensitive?", console=console, default=default_case_sensitive
            )
        threshold: float | None = None
        if engine == "fuzzy":
            presets = ", ".join(SearchSettings.FUZZY_PRESETS)
            answer = Prompt.ask(
                f"Fuzziness ({presets}, or a similarity above 0 up to 1)",
                console=console,
                default=default_threshold,
            )
            try:
                threshold = SearchSettings.parse_fuzzy_threshold(answer)
            except ValueError as exc:
                error_console.print(f"Error: {exc}", style="bold red")
                return
        InteractiveMenu._run_safely(
            run_search,
            content=content,
            engine=engine,
            case_sensitive=case_sensitive,
            threshold=threshold,
            fuzziness=None,
            export=None,
            format_=None,
        )

    @staticmethod
    def _sources_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Sources", [("1", "List"), ("2", "Add"), ("3", "Remove"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(source_list)
            elif choice == "2":
                path = Prompt.ask("File or folder to register", console=console)
                InteractiveMenu._run_safely(source_add, path=path)
            elif choice == "3":
                path_or_id = Prompt.ask("Source id or path to remove", console=console)
                InteractiveMenu._run_safely(source_remove, path_or_id=path_or_id, force=False)

    @staticmethod
    def _index_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
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
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "4", "5", "6", "7", "0"])
            if choice == "0":
                return
            if choice == "1":
                target = Prompt.ask(
                    "Source id or path (blank for all pending sources)", console=console, default=""
                ).strip()
                wait = Confirm.ask("Wait for the run to finish?", console=console, default=False)
                InteractiveMenu._run_safely(
                    index_run, target=target or None, wait=wait, force=False
                )
            elif choice == "2":
                target = Prompt.ask(
                    "Source id or path (blank to retry every failed file)",
                    console=console,
                    default="",
                ).strip()
                wait = Confirm.ask("Wait for the run to finish?", console=console, default=False)
                InteractiveMenu._run_safely(
                    index_restart, target=target or None, wait=wait, force=False
                )
            elif choice == "3":
                target = Prompt.ask(
                    "Source id or path (blank for overall status)", console=console, default=""
                ).strip()
                InteractiveMenu._run_safely(index_status, target=target or None, as_json=False)
            elif choice == "4":
                InteractiveMenu._run_safely(index_stop, force=False)
            elif choice == "5":
                InteractiveMenu._run_safely(index_pause, force=False)
            elif choice == "6":
                InteractiveMenu._run_safely(index_resume)
            elif choice == "7":
                target = Prompt.ask(
                    "Source id or path (blank for all sources)", console=console, default=""
                ).strip()
                InteractiveMenu._run_safely(
                    index_history, target=target or None, limit=10, as_json=False
                )

    @staticmethod
    def _settings_gpu_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > GPU",
                [("1", "Enable"), ("2", "Disable"), ("3", "Status"), ("0", "Back")],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(gpu_enable)
            elif choice == "2":
                InteractiveMenu._run_safely(gpu_disable)
            elif choice == "3":
                InteractiveMenu._run_safely(gpu_status)

    @staticmethod
    def _settings_snippet_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Search > Snippet", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(snippet_show)
            elif choice == "2":
                chars = IntPrompt.ask(
                    "Characters of context on each side of a match", console=console
                )
                InteractiveMenu._run_safely(snippet_set, chars=chars)

    @staticmethod
    def _settings_export_format_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Search > Export Format", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(export_format_show)
            elif choice == "2":
                format_ = Prompt.ask(
                    "Format", console=console, choices=list(SearchSettings.EXPORT_FORMATS)
                )
                InteractiveMenu._run_safely(export_format_set, format_=format_)

    @staticmethod
    def _settings_search_engine_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Search > Engine", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(search_engine_show)
            elif choice == "2":
                engine = Prompt.ask("Engine", console=console, choices=list(SearchSettings.ENGINES))
                InteractiveMenu._run_safely(search_engine_set, engine=engine)

    @staticmethod
    def _settings_case_sensitive_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Search > Case Sensitive",
                [("1", "Show"), ("2", "Enable"), ("3", "Disable"), ("0", "Back")],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(case_sensitive_show)
            elif choice == "2":
                InteractiveMenu._run_safely(case_sensitive_enable)
            elif choice == "3":
                InteractiveMenu._run_safely(case_sensitive_disable)

    @staticmethod
    def _settings_fuzzy_threshold_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Search > Fuzzy Threshold",
                [("1", "Show"), ("2", "Set"), ("0", "Back")],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(fuzzy_threshold_show)
            elif choice == "2":
                presets = ", ".join(SearchSettings.FUZZY_PRESETS)
                threshold = Prompt.ask(
                    f"Threshold ({presets}, or a similarity above 0 up to 1)", console=console
                )
                InteractiveMenu._run_safely(fuzzy_threshold_set, threshold=threshold)

    @staticmethod
    def _settings_search_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Search",
                [
                    ("1", "Snippet"),
                    ("2", "Export Format"),
                    ("3", "Engine"),
                    ("4", "Case Sensitive"),
                    ("5", "Fuzzy Threshold"),
                    ("0", "Back"),
                ],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "4", "5", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_snippet_menu()
            elif choice == "2":
                InteractiveMenu._settings_export_format_menu()
            elif choice == "3":
                InteractiveMenu._settings_search_engine_menu()
            elif choice == "4":
                InteractiveMenu._settings_case_sensitive_menu()
            elif choice == "5":
                InteractiveMenu._settings_fuzzy_threshold_menu()

    @staticmethod
    def _settings_removed_retention_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Index > Removed Retention", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(removed_retention_show)
            elif choice == "2":
                minutes = IntPrompt.ask(
                    "Minutes to keep a removed source before it's purged", console=console
                )
                InteractiveMenu._run_safely(removed_retention_set, minutes=minutes)

    @staticmethod
    def _settings_retry_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Ocr > Retry", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(retry_show)
            elif choice == "2":
                attempts = IntPrompt.ask(
                    "Times to retry a file's OCR after a transient failure", console=console
                )
                InteractiveMenu._run_safely(retry_set, attempts=attempts)

    @staticmethod
    def _settings_thread_workers_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Index > Thread Workers", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(thread_workers_show)
            elif choice == "2":
                choices = [str(n) for n in range(IndexSettings.THREAD_WORKERS_MAX + 1)] + [
                    IndexSettings.THREAD_WORKERS_AUTO
                ]
                value = Prompt.ask(
                    f"0 (disable), 1-{IndexSettings.THREAD_WORKERS_MAX}, "
                    f"or '{IndexSettings.THREAD_WORKERS_AUTO}'",
                    console=console,
                    choices=choices,
                )
                InteractiveMenu._run_safely(thread_workers_set, value=value)

    @staticmethod
    def _settings_stale_lock_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Index > Stale Lock", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(stale_lock_show)
            elif choice == "2":
                value = Prompt.ask(
                    "Auto-clear a lock left behind by a run that didn't exit cleanly",
                    console=console,
                    choices=list(IndexSettings.STALE_LOCK_VALUES),
                )
                InteractiveMenu._run_safely(stale_lock_set, value=value)

    @staticmethod
    def _settings_integrity_check_interval_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Db > Integrity Check > Interval",
                [("1", "Show"), ("2", "Set"), ("0", "Back")],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(integrity_check_interval_show)
            elif choice == "2":
                minutes = IntPrompt.ask(
                    "Minutes between automatic integrity checks when 'auto'", console=console
                )
                InteractiveMenu._run_safely(integrity_check_interval_set, minutes=minutes)

    @staticmethod
    def _settings_integrity_check_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Db > Integrity Check",
                [("1", "Show"), ("2", "Set"), ("3", "Interval"), ("0", "Back")],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(integrity_check_show)
            elif choice == "2":
                value = Prompt.ask(
                    "Run 'PRAGMA integrity_check' automatically when the database is opened",
                    console=console,
                    choices=list(DbSettings.INTEGRITY_CHECK_VALUES),
                )
                InteractiveMenu._run_safely(integrity_check_set, value=value)
            elif choice == "3":
                InteractiveMenu._settings_integrity_check_interval_menu()

    @staticmethod
    def _settings_engine_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Ocr > Engine", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(engine_show)
            elif choice == "2":
                value = Prompt.ask(
                    "How thoroughly OCR looks for rotated text",
                    console=console,
                    choices=list(OcrSettings.ENGINE_MODES),
                )
                InteractiveMenu._run_safely(engine_set, value=value)

    @staticmethod
    def _settings_stability_check_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Index > Stability Check", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(stability_check_show)
            elif choice == "2":
                seconds = FloatPrompt.ask(
                    "Seconds a file must stay unchanged before it's indexed (0 disables)",
                    console=console,
                )
                InteractiveMenu._run_safely(stability_check_set, seconds=seconds)

    @staticmethod
    def _settings_index_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Index",
                [
                    ("1", "Removed Retention"),
                    ("2", "Thread Workers"),
                    ("3", "Stale Lock"),
                    ("4", "Stability Check"),
                    ("0", "Back"),
                ],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "4", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_removed_retention_menu()
            elif choice == "2":
                InteractiveMenu._settings_thread_workers_menu()
            elif choice == "3":
                InteractiveMenu._settings_stale_lock_menu()
            elif choice == "4":
                InteractiveMenu._settings_stability_check_menu()

    @staticmethod
    def _settings_ocr_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Ocr", [("1", "Retry"), ("2", "Engine"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_retry_menu()
            elif choice == "2":
                InteractiveMenu._settings_engine_menu()

    @staticmethod
    def _stats_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu("Stats", [("1", "Show"), ("2", "Reset"), ("0", "Back")])
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(stats_show)
            elif choice == "2":
                InteractiveMenu._run_safely(stats_reset, force=False)

    @staticmethod
    def _settings_db_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu("Settings > Db", [("1", "Integrity Check"), ("0", "Back")])
            choice = InteractiveMenu._prompt_choice(["1", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_integrity_check_menu()

    @staticmethod
    def _settings_log_level_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Logs > Level", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(log_level_show)
            elif choice == "2":
                value = Prompt.ask(
                    "Log level for VethuQ's log files",
                    console=console,
                    choices=list(LogSettings.LEVEL_VALUES),
                )
                InteractiveMenu._run_safely(log_level_set, value=value)

    @staticmethod
    def _settings_log_retention_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Logs > Retention", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(log_retention_show)
            elif choice == "2":
                days = IntPrompt.ask("Days of daily log files to keep", console=console)
                InteractiveMenu._run_safely(log_retention_set, days=days)

    @staticmethod
    def _settings_logs_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings > Logs", [("1", "Level"), ("2", "Retention"), ("0", "Back")]
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_log_level_menu()
            elif choice == "2":
                InteractiveMenu._settings_log_retention_menu()

    @staticmethod
    def _settings_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Settings",
                [
                    ("1", "GPU"),
                    ("2", "Search"),
                    ("3", "Index"),
                    ("4", "Ocr"),
                    ("5", "Db"),
                    ("6", "Logs"),
                    ("0", "Back"),
                ],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "4", "5", "6", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_gpu_menu()
            elif choice == "2":
                InteractiveMenu._settings_search_menu()
            elif choice == "3":
                InteractiveMenu._settings_index_menu()
            elif choice == "4":
                InteractiveMenu._settings_ocr_menu()
            elif choice == "5":
                InteractiveMenu._settings_db_menu()
            elif choice == "6":
                InteractiveMenu._settings_logs_menu()

    @staticmethod
    def _db_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu("Db", [("1", "Integrity Check"), ("0", "Back")])
            choice = InteractiveMenu._prompt_choice(["1", "0"])
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(db_integrity_check)

    @staticmethod
    def _logs_menu() -> None:
        while True:
            console.print()
            InteractiveMenu._print_menu(
                "Logs",
                [("1", "Database"), ("2", "Index"), ("3", "Ui"), ("4", "Cli"), ("0", "Back")],
            )
            choice = InteractiveMenu._prompt_choice(["1", "2", "3", "4", "0"])
            if choice == "0":
                return
            component = ("database", "index", "ui", "cli")[int(choice) - 1]
            lines = IntPrompt.ask(
                "Number of recent log entries to show",
                console=console,
                default=LogsCommand.DEFAULT_TAIL,
            )
            InteractiveMenu._run_safely(
                LogsCommand.run,
                component=component,
                tail=lines,
                follow=False,
                level=None,
                day=None,
                export=None,
            )

    @staticmethod
    def run() -> None:
        """Show the interactive shell used when `vethuq` is invoked with no subcommand."""
        InteractiveMenu._print_banner()
        try:
            while True:
                console.print()
                InteractiveMenu._print_menu(
                    "Main Menu",
                    [
                        ("1", "Search"),
                        ("2", "Sources"),
                        ("3", "Index"),
                        ("4", "Settings"),
                        ("5", "Stats"),
                        ("6", "Db"),
                        ("7", "Logs"),
                        ("8", "Exit"),
                    ],
                )
                choice = InteractiveMenu._prompt_choice(["1", "2", "3", "4", "5", "6", "7", "8"])
                if choice == "8":
                    break
                if choice == "1":
                    InteractiveMenu._search_action()
                elif choice == "2":
                    InteractiveMenu._sources_menu()
                elif choice == "3":
                    InteractiveMenu._index_menu()
                elif choice == "4":
                    InteractiveMenu._settings_menu()
                elif choice == "5":
                    InteractiveMenu._stats_menu()
                elif choice == "6":
                    InteractiveMenu._db_menu()
                elif choice == "7":
                    InteractiveMenu._logs_menu()
        except _Quit:
            pass
        console.print()
        console.print("Goodbye.", style="bright_black")
