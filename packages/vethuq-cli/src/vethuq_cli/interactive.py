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
from rich.table import Table
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
from vethuq_cli.db import backup_create as db_backup_create
from vethuq_cli.db import backup_delete as db_backup_delete
from vethuq_cli.db import backup_list as db_backup_list
from vethuq_cli.db import integrity_check as db_integrity_check
from vethuq_cli.db import repair as db_repair
from vethuq_cli.db import reset as db_reset
from vethuq_cli.db import restore as db_restore
from vethuq_cli.index.commands import history as index_history
from vethuq_cli.index.commands import pause as index_pause
from vethuq_cli.index.commands import reindex_file as index_reindex_file
from vethuq_cli.index.commands import reindex_source as index_reindex_source
from vethuq_cli.index.commands import restart as index_restart
from vethuq_cli.index.commands import resume as index_resume
from vethuq_cli.index.commands import run as index_run
from vethuq_cli.index.commands import status as index_status
from vethuq_cli.index.commands import stop as index_stop
from vethuq_cli.logs import LogsCommand
from vethuq_cli.search import search as run_search
from vethuq_cli.settings import (
    backup_interval_set,
    backup_interval_show,
    backup_retention_set,
    backup_retention_show,
    backup_set,
    backup_show,
    backups_location_reset,
    backups_location_set,
    backups_location_show,
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
    location_set,
    location_show,
    log_level_set,
    log_level_show,
    log_retention_set,
    log_retention_show,
    proximity_distance_set,
    proximity_distance_show,
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
from vethuq_cli.source import SourceSort
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
        console.print(
            Panel(
                "",
                title=Text(APP_NAME, style=Theme.BRAND),
                title_align="left",
                subtitle=Text(APP_TAGLINE, style="bright_black"),
                subtitle_align="left",
                border_style=Theme.PRIMARY,
                expand=True,
            )
        )

    @staticmethod
    def _menu_panel(title: str, items: list[tuple[str, str]]) -> Panel:
        """A menu as a full-width panel: its title, then one numbered row per item.

        Back (`0`) and Exit read dimmer than the real choices.
        """
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style="bright_black", no_wrap=True)
        table.add_column(no_wrap=False, overflow="fold")
        for key, label in items:
            leaves = key == "0" or label == "Exit"
            table.add_row(key, Text(label, style="bright_black" if leaves else "white"))
        return Panel(
            table,
            title=Text(title, style="bold"),
            title_align="left",
            subtitle=Text("Enter a number - q to quit", style="bright_black"),
            subtitle_align="left",
            border_style="bright_black",
            expand=True,
        )

    @staticmethod
    def _select(title: str, items: list[tuple[str, str]]) -> str:
        """Show a menu and return the chosen key; `q` leaves the whole shell."""
        console.print(InteractiveMenu._menu_panel(title, items))
        keys = [key for key, _ in items]
        while True:
            raw = Prompt.ask("Select", console=console).strip().lower()
            if raw in ("q", "quit"):
                raise _Quit
            if raw in keys:
                return raw
            console.print(
                f"Invalid selection. Choose one of: {', '.join(keys)}, or q to quit.",
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
    def _ask_sort() -> tuple[SourceSort.Order, SourceSort.By]:
        """Ask how to sort a listing; Enter keeps the default (filename, ascending)."""
        by = Prompt.ask(
            "Sort by",
            console=console,
            default=SourceSort.By.FILENAME.value,
            choices=[b.value for b in SourceSort.By],
        )
        order = Prompt.ask(
            "Sort order",
            console=console,
            default=SourceSort.Order.ASC.value,
            choices=[o.value for o in SourceSort.Order],
        )
        return SourceSort.Order(order), SourceSort.By(by)

    @staticmethod
    def _ask_export() -> tuple[str | None, str | None]:
        """Ask where (and as what format) to export a listing; `(None, None)` to just print it."""
        output = Prompt.ask("Export to file (blank to just print)", console=console, default="")
        if not output.strip():
            return None, None
        storage = open_storage()
        try:
            default_format = SearchSettings.get_export_format(storage)
        finally:
            storage.close()
        format_ = Prompt.ask(
            "Export format",
            console=console,
            default=default_format,
            choices=list(SearchSettings.EXPORT_FORMATS),
        )
        return output.strip(), format_

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
            default_distance = SearchSettings.get_proximity_distance_setting(storage)
        finally:
            storage.close()
        engine = Prompt.ask(
            "Engine", console=console, choices=list(SearchSettings.ENGINES), default=default_engine
        )
        # Only `like`, `lexical`, `fuzzy` and `all` (which includes them) have a choice to make:
        # `exact` is always case-sensitive while `full-text` and `proximity` never are,
        # so asking would have no effect. `all` uses the stored threshold and distance.
        case_sensitive: bool | None = None
        if engine in (SearchSettings.ENGINE_ALL, "like", "lexical", "fuzzy"):
            case_sensitive = Confirm.ask(
                "Case-sensitive?", console=console, default=default_case_sensitive
            )
        threshold: str | None = None
        if engine == "fuzzy":
            presets = ", ".join(SearchSettings.FUZZY_PRESETS)
            threshold = Prompt.ask(
                f"Fuzziness ({presets}, a percentage or a similarity 0-1)",
                console=console,
                default=default_threshold,
            )
        distance: str | None = None
        if engine == "proximity":
            presets = ", ".join(SearchSettings.PROXIMITY_PRESETS)
            distance = Prompt.ask(
                f"Distance ({presets}, or words 1-{SearchSettings.PROXIMITY_MAX_DISTANCE})",
                console=console,
                default=default_distance,
            )
        InteractiveMenu._run_safely(
            run_search,
            content=content,
            engine=engine,
            case_sensitive=case_sensitive,
            threshold=threshold,
            fuzziness=None,
            distance=distance,
            export=None,
            format_=None,
        )

    @staticmethod
    def _sources_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Sources",
                [
                    ("1", "List"),
                    ("2", "List Files"),
                    ("3", "Add"),
                    ("4", "Remove"),
                    ("0", "Back"),
                ],
            )
            if choice == "0":
                return
            if choice == "1":
                sort, sort_by = InteractiveMenu._ask_sort()
                export, format_ = InteractiveMenu._ask_export()
                InteractiveMenu._run_safely(
                    source_list,
                    target=None,
                    detail=False,
                    export=export,
                    format_=format_,
                    sort=sort,
                    sort_by=sort_by,
                )
            elif choice == "2":
                target = Prompt.ask("Source id or path to list the files of", console=console)
                detail = Confirm.ask("Show detailed information?", console=console, default=False)
                sort, sort_by = InteractiveMenu._ask_sort()
                export, format_ = InteractiveMenu._ask_export()
                InteractiveMenu._run_safely(
                    source_list,
                    target=target.strip(),
                    detail=detail,
                    export=export,
                    format_=format_,
                    sort=sort,
                    sort_by=sort_by,
                )
            elif choice == "3":
                path = Prompt.ask("File or folder to register", console=console)
                InteractiveMenu._run_safely(source_add, path=path)
            elif choice == "4":
                path_or_id = Prompt.ask("Source id or path to remove", console=console)
                InteractiveMenu._run_safely(source_remove, path_or_id=path_or_id, force=False)

    @staticmethod
    def _index_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Index",
                [
                    ("1", "Run"),
                    ("2", "Restart"),
                    ("3", "Status"),
                    ("4", "Stop"),
                    ("5", "Pause"),
                    ("6", "Resume"),
                    ("7", "History"),
                    ("8", "Reindex source"),
                    ("9", "Reindex file"),
                    ("0", "Back"),
                ],
            )
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
            elif choice == "8":
                target = Prompt.ask("Source id or path to re-index", console=console).strip()
                if not target:
                    continue
                wait = Confirm.ask("Wait for the run to finish?", console=console, default=False)
                InteractiveMenu._run_safely(
                    index_reindex_source, target=target, wait=wait, force=False
                )
            elif choice == "9":
                file = Prompt.ask("File id or path to re-index", console=console).strip()
                if not file:
                    continue
                source = Prompt.ask(
                    "Source id or path (blank unless the file is under several sources)",
                    console=console,
                    default="",
                ).strip()
                wait = Confirm.ask("Wait for the run to finish?", console=console, default=False)
                InteractiveMenu._run_safely(
                    index_reindex_file, file=file, source=source or None, wait=wait, force=False
                )

    @staticmethod
    def _settings_gpu_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > GPU",
                [("1", "Enable"), ("2", "Disable"), ("3", "Status"), ("0", "Back")],
            )
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
            choice = InteractiveMenu._select(
                "Settings > Search > Snippet", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Search > Export Format", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Search > Engine", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Search > Case Sensitive",
                [("1", "Show"), ("2", "Enable"), ("3", "Disable"), ("0", "Back")],
            )
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
            choice = InteractiveMenu._select(
                "Settings > Search > Fuzzy Threshold", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(fuzzy_threshold_show)
            elif choice == "2":
                presets = ", ".join(SearchSettings.FUZZY_PRESETS)
                threshold = Prompt.ask(
                    f"Threshold ({presets}, a percentage or a similarity 0-1)", console=console
                )
                InteractiveMenu._run_safely(fuzzy_threshold_set, threshold=threshold)

    @staticmethod
    def _settings_proximity_distance_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Search > Proximity Distance",
                [("1", "Show"), ("2", "Set"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(proximity_distance_show)
            elif choice == "2":
                presets = ", ".join(SearchSettings.PROXIMITY_PRESETS)
                distance = Prompt.ask(
                    f"Distance ({presets}, or words 1-{SearchSettings.PROXIMITY_MAX_DISTANCE})",
                    console=console,
                )
                InteractiveMenu._run_safely(proximity_distance_set, distance=distance)

    @staticmethod
    def _settings_search_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Search",
                [
                    ("1", "Snippet"),
                    ("2", "Export Format"),
                    ("3", "Engine"),
                    ("4", "Case Sensitive"),
                    ("5", "Fuzzy Threshold"),
                    ("6", "Proximity Distance"),
                    ("0", "Back"),
                ],
            )
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
            elif choice == "6":
                InteractiveMenu._settings_proximity_distance_menu()

    @staticmethod
    def _settings_removed_retention_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Index > Removed Retention", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Ocr > Retry", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Index > Thread Workers", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Index > Stale Lock", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Db > Integrity Check > Interval",
                [("1", "Show"), ("2", "Set"), ("0", "Back")],
            )
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
            choice = InteractiveMenu._select(
                "Settings > Db > Integrity Check",
                [("1", "Show"), ("2", "Set"), ("3", "Interval"), ("0", "Back")],
            )
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
    def _settings_backup_interval_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Db > Backup > Interval",
                [("1", "Show"), ("2", "Set"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(backup_interval_show)
            elif choice == "2":
                minutes = IntPrompt.ask("Minutes between automatic backups", console=console)
                InteractiveMenu._run_safely(backup_interval_set, value=minutes)

    @staticmethod
    def _settings_backup_retention_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Db > Backup > Retention",
                [("1", "Show"), ("2", "Set"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(backup_retention_show)
            elif choice == "2":
                days = IntPrompt.ask("Days automatic backups are kept", console=console)
                InteractiveMenu._run_safely(backup_retention_set, value=days)

    @staticmethod
    def _settings_backup_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Db > Backup",
                [("1", "Show"), ("2", "Set"), ("3", "Interval"), ("4", "Retention"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(backup_show)
            elif choice == "2":
                value = Prompt.ask(
                    "Take a compressed backup automatically when the database is opened",
                    console=console,
                    choices=list(DbSettings.BACKUP_VALUES),
                )
                InteractiveMenu._run_safely(backup_set, value=value)
            elif choice == "3":
                InteractiveMenu._settings_backup_interval_menu()
            elif choice == "4":
                InteractiveMenu._settings_backup_retention_menu()

    @staticmethod
    def _settings_engine_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Ocr > Engine", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Index > Stability Check", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Index",
                [
                    ("1", "Removed Retention"),
                    ("2", "Thread Workers"),
                    ("3", "Stale Lock"),
                    ("4", "Stability Check"),
                    ("0", "Back"),
                ],
            )
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
            choice = InteractiveMenu._select(
                "Settings > Ocr", [("1", "Retry"), ("2", "Engine"), ("0", "Back")]
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_retry_menu()
            elif choice == "2":
                InteractiveMenu._settings_engine_menu()

    @staticmethod
    def _stats_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Stats", [("1", "Show"), ("2", "Reset"), ("0", "Back")]
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(stats_show)
            elif choice == "2":
                InteractiveMenu._run_safely(stats_reset, force=False)

    @staticmethod
    def _settings_db_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Db", [("1", "Integrity Check"), ("2", "Backup"), ("0", "Back")]
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_integrity_check_menu()
            elif choice == "2":
                InteractiveMenu._settings_backup_menu()

    @staticmethod
    def _settings_log_level_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Logs > Level", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Logs > Retention", [("1", "Show"), ("2", "Set"), ("0", "Back")]
            )
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
            choice = InteractiveMenu._select(
                "Settings > Logs", [("1", "Level"), ("2", "Retention"), ("0", "Back")]
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._settings_log_level_menu()
            elif choice == "2":
                InteractiveMenu._settings_log_retention_menu()

    @staticmethod
    def _settings_location_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Location",
                [("1", "Show"), ("2", "Set"), ("3", "Backups"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(location_show)
            elif choice == "2":
                path = Prompt.ask("Folder to keep VethuQ's data in", console=console)
                InteractiveMenu._run_safely(location_set, path=path.strip().strip('"'), force=False)
            elif choice == "3":
                InteractiveMenu._settings_backups_location_menu()

    @staticmethod
    def _settings_backups_location_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings > Location > Backups",
                [("1", "Show"), ("2", "Set"), ("3", "Reset"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(backups_location_show)
            elif choice == "2":
                path = Prompt.ask("Folder to keep database backups in", console=console)
                InteractiveMenu._run_safely(
                    backups_location_set, path=path.strip().strip('"'), force=False
                )
            elif choice == "3":
                InteractiveMenu._run_safely(backups_location_reset)

    @staticmethod
    def _settings_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Settings",
                [
                    ("1", "GPU"),
                    ("2", "Search"),
                    ("3", "Index"),
                    ("4", "Ocr"),
                    ("5", "Db"),
                    ("6", "Logs"),
                    ("7", "Location"),
                    ("0", "Back"),
                ],
            )
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
            elif choice == "7":
                InteractiveMenu._settings_location_menu()

    @staticmethod
    def _db_backup_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Db > Backup",
                [("1", "Create"), ("2", "List"), ("3", "Delete"), ("0", "Back")],
            )
            if choice == "0":
                return
            if choice == "1":
                name = Prompt.ask("Name for the snapshot (blank for a timestamp)", console=console)
                InteractiveMenu._run_safely(db_backup_create, name=name.strip() or None)
            elif choice == "2":
                InteractiveMenu._run_safely(db_backup_list)
            elif choice == "3":
                name = Prompt.ask("Name of the backup to delete", console=console)
                InteractiveMenu._run_safely(db_backup_delete, name=name, force=False)

    @staticmethod
    def _db_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Db",
                [
                    ("1", "Integrity Check"),
                    ("2", "Backup"),
                    ("3", "Restore"),
                    ("4", "Repair"),
                    ("5", "Reset"),
                    ("0", "Back"),
                ],
            )
            if choice == "0":
                return
            if choice == "1":
                InteractiveMenu._run_safely(db_integrity_check)
            elif choice == "2":
                InteractiveMenu._db_backup_menu()
            elif choice == "3":
                source = Prompt.ask("Backup name or file path to restore", console=console)
                InteractiveMenu._run_safely(db_restore, source=source, force=False)
            elif choice == "4":
                InteractiveMenu._run_safely(db_repair, force=False)
            elif choice == "5":
                InteractiveMenu._run_safely(db_reset, force=False)

    @staticmethod
    def _logs_menu() -> None:
        while True:
            choice = InteractiveMenu._select(
                "Logs",
                [("1", "Database"), ("2", "Index"), ("3", "Ui"), ("4", "Cli"), ("0", "Back")],
            )
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
                choice = InteractiveMenu._select(
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
