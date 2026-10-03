"""`vethuq settings ...` commands for configuring VethuQ."""

from __future__ import annotations

import typer
from rich.text import Text
from vethuq_core.settings import (
    DbSettings,
    GpuSettings,
    IndexSettings,
    LogSettings,
    OcrSettings,
    SearchSettings,
    SourceSettings,
)
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Manage VethuQ settings.")
gpu_app = typer.Typer(help="Configure whether OCR should use the GPU when available.")
search_app = typer.Typer(help="Configure `search` behavior.")
snippet_app = typer.Typer(help="Configure how much context `search` shows around a match.")
export_format_app = typer.Typer(help="Configure the default format `search --export` writes to.")
search_engine_app = typer.Typer(help="Configure the default engine `search` matches with.")
fuzzy_app = typer.Typer(help="Configure the `fuzzy` search engine.")
fuzzy_threshold_app = typer.Typer(
    help="Configure how close a word must be to your query for `fuzzy` search to match it."
)
proximity_app = typer.Typer(help="Configure the `proximity` search engine.")
proximity_distance_app = typer.Typer(
    help="Configure how many words may separate your first and last word for `proximity` search."
)
case_sensitive_app = typer.Typer(
    help="Configure whether `search` matches case by default (only the 'like' engine honours it)."
)
index_app = typer.Typer(help="Configure indexing behavior.")
removed_retention_app = typer.Typer(
    help="Configure, in minutes, how long a removed source is kept before it's purged from the DB."
)
retry_app = typer.Typer(
    help="Configure how many times to retry a file's OCR after a transient failure."
)
ocr_app = typer.Typer(help="Configure OCR behavior.")
stability_check_app = typer.Typer(
    help="Configure, in seconds, how long a file must stay unchanged before it's indexed."
)
thread_workers_app = typer.Typer(help="Configure how many worker threads background indexing uses.")
stale_lock_app = typer.Typer(
    help="Configure whether a lock left behind by a run that didn't exit cleanly "
    "is auto-cleared on the next run."
)
db_app = typer.Typer(help="Configure database behavior.")
integrity_check_app = typer.Typer(
    help="Configure whether 'PRAGMA integrity_check' runs automatically when the "
    "database is opened."
)
integrity_check_interval_app = typer.Typer(
    help="Configure, in minutes, how often automatic integrity checks run when "
    "'integrity-check' is 'auto'."
)
engine_app = typer.Typer(
    help="Configure how thoroughly OCR looks for rotated text: quick, moderate or deep."
)
logs_app = typer.Typer(help="Configure logging.")
log_level_app = typer.Typer(help="Configure how verbose VethuQ's log files are.")
log_retention_app = typer.Typer(help="Configure how many days of daily log files are kept.")
app.add_typer(gpu_app, name="gpu")
app.add_typer(search_app, name="search")
search_app.add_typer(snippet_app, name="snippet")
search_app.add_typer(export_format_app, name="export-format")
search_app.add_typer(search_engine_app, name="engine")
search_app.add_typer(case_sensitive_app, name="case-sensitive")
search_app.add_typer(fuzzy_app, name="fuzzy")
fuzzy_app.add_typer(fuzzy_threshold_app, name="threshold")
search_app.add_typer(proximity_app, name="proximity")
proximity_app.add_typer(proximity_distance_app, name="distance")
app.add_typer(index_app, name="index")
index_app.add_typer(removed_retention_app, name="removed-retention")
index_app.add_typer(stability_check_app, name="stability-check")
index_app.add_typer(thread_workers_app, name="thread-workers")
index_app.add_typer(stale_lock_app, name="stale-lock")
app.add_typer(ocr_app, name="ocr")
ocr_app.add_typer(retry_app, name="retry")
ocr_app.add_typer(engine_app, name="engine")
app.add_typer(db_app, name="db")
db_app.add_typer(integrity_check_app, name="integrity-check")
integrity_check_app.add_typer(integrity_check_interval_app, name="interval")
app.add_typer(logs_app, name="logs")
logs_app.add_typer(log_level_app, name="level")
logs_app.add_typer(log_retention_app, name="retention")


@gpu_app.command("enable")
def gpu_enable() -> None:
    """Enable GPU use for OCR.

    Only takes effect if a CUDA-capable PaddlePaddle build with a visible GPU
    is actually installed - otherwise OCR silently falls back to CPU.
    """
    storage = open_storage()
    try:
        GpuSettings.set_enabled(storage, True)
        console.print(
            "GPU enabled. It will be used next time OCR runs, if a CUDA-capable "
            "PaddleOCR build is installed; otherwise CPU is used.",
            style=Theme.OK,
        )
    finally:
        storage.close()


@gpu_app.command("disable")
def gpu_disable() -> None:
    """Disable GPU use for OCR (the default) - OCR always runs on CPU."""
    storage = open_storage()
    try:
        GpuSettings.set_enabled(storage, False)
        console.print("GPU disabled. OCR will run on CPU.", style="bright_black")
    finally:
        storage.close()


@gpu_app.command("status")
def gpu_status() -> None:
    """Show whether GPU use is currently enabled."""
    storage = open_storage()
    try:
        enabled = GpuSettings.is_enabled(storage)
        line = Text("GPU: ")
        line.append(
            "enabled" if enabled else "disabled", style="green" if enabled else "bright_black"
        )
        console.print(line)
    finally:
        storage.close()


@snippet_app.command("show")
def snippet_show() -> None:
    """Show how many characters of context `search` shows around a match."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "Search snippet context: ",
                (str(SearchSettings.get_snippet_context_chars(storage)), Theme.VALUE),
                " characters",
            )
        )
    finally:
        storage.close()


@snippet_app.command("set")
def snippet_set(
    chars: int = typer.Argument(..., help="Characters of context to show on each side of a match."),
) -> None:
    """Set how many characters of context `search` shows around a match."""
    storage = open_storage()
    try:
        try:
            SearchSettings.set_snippet_context_chars(storage, chars)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Search snippet context set to ", (str(chars), Theme.VALUE), " characters."
            )
        )
    finally:
        storage.close()


@export_format_app.command("show")
def export_format_show() -> None:
    """Show the default format `search --export` writes to when none is given."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "Search export format: ", (SearchSettings.get_export_format(storage), Theme.VALUE)
            )
        )
    finally:
        storage.close()


@export_format_app.command("set")
def export_format_set(
    format_: str = typer.Argument(
        ..., metavar="FORMAT", help=f"One of: {', '.join(SearchSettings.EXPORT_FORMATS)}."
    ),
) -> None:
    """Set the default format `search --export` writes to when none is given."""
    storage = open_storage()
    try:
        try:
            SearchSettings.set_export_format(storage, format_)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Search export format set to ", (format_, Theme.VALUE), "."))
    finally:
        storage.close()


@search_engine_app.command("show")
def search_engine_show() -> None:
    """Show the engine `search` uses when `--engine` isn't given."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble("Search engine: ", (SearchSettings.get_engine(storage), Theme.VALUE))
        )
    finally:
        storage.close()


@search_engine_app.command("set")
def search_engine_set(
    engine: str = typer.Argument(
        ..., metavar="ENGINE", help=f"One of: {', '.join(SearchSettings.ENGINES)}."
    ),
) -> None:
    """Set the engine `search` uses when `--engine` isn't given."""
    storage = open_storage()
    try:
        try:
            SearchSettings.set_engine(storage, engine)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Search engine set to ", (engine, Theme.VALUE), "."))
    finally:
        storage.close()


@case_sensitive_app.command("show")
def case_sensitive_show() -> None:
    """Show whether `search` matches case by default."""
    storage = open_storage()
    try:
        enabled = SearchSettings.is_case_sensitive(storage)
        line = Text("Search case-sensitive: ")
        line.append("enabled" if enabled else "disabled", style=Theme.VALUE)
        console.print(line)
    finally:
        storage.close()


@case_sensitive_app.command("enable")
def case_sensitive_enable() -> None:
    """Make `search` match case by default ('like'/'fuzzy'; `--no-case-sensitive` overrides)."""
    storage = open_storage()
    try:
        SearchSettings.set_case_sensitive(storage, True)
        console.print("Search will match case by default.")
    finally:
        storage.close()


@case_sensitive_app.command("disable")
def case_sensitive_disable() -> None:
    """Make `search` ignore case by default (the default)."""
    storage = open_storage()
    try:
        SearchSettings.set_case_sensitive(storage, False)
        console.print("Search will ignore case by default.")
    finally:
        storage.close()


@fuzzy_threshold_app.command("show")
def fuzzy_threshold_show() -> None:
    """Show the minimum similarity `search --engine fuzzy` accepts when none is given."""
    storage = open_storage()
    try:
        setting = SearchSettings.get_fuzzy_threshold_setting(storage)
        value = SearchSettings.get_fuzzy_threshold(storage)
        console.print(
            Text.assemble(
                "Search fuzzy threshold: ", (setting, Theme.VALUE), f" (similarity {value:.0%})"
            )
        )
    finally:
        storage.close()


@fuzzy_threshold_app.command("set")
def fuzzy_threshold_set(
    threshold: str = typer.Argument(
        ...,
        metavar="THRESHOLD",
        help=(
            f"One of: {', '.join(SearchSettings.FUZZY_PRESETS)} - or a percentage (e.g. 75%) "
            "or a similarity above 0 and up to 1 (e.g. 0.75)."
        ),
    ),
) -> None:
    """Set the minimum similarity `search --engine fuzzy` accepts when none is given.

    `strict` (90%) finds little beyond plurals and other one-letter variants of longer
    words; `balanced` (80%, the default) also catches a typo in a longer word; `loose`
    (65%) catches heavier OCR damage such as `Museurn` for `Museum`, with more noise.
    """
    storage = open_storage()
    try:
        try:
            SearchSettings.set_fuzzy_threshold(storage, threshold)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Search fuzzy threshold set to ", (threshold.strip().lower(), Theme.VALUE), "."
            )
        )
    finally:
        storage.close()


@proximity_distance_app.command("show")
def proximity_distance_show() -> None:
    """Show the most words `search --engine proximity` allows between its first and last word."""
    storage = open_storage()
    try:
        setting = SearchSettings.get_proximity_distance_setting(storage)
        value = SearchSettings.get_proximity_distance(storage)
        console.print(
            Text.assemble(
                "Search proximity distance: ", (setting, Theme.VALUE), f" ({value} words)"
            )
        )
    finally:
        storage.close()


@proximity_distance_app.command("set")
def proximity_distance_set(
    distance: str = typer.Argument(
        ...,
        metavar="DISTANCE",
        help=(
            f"One of: {', '.join(SearchSettings.PROXIMITY_PRESETS)} - or a number of words from "
            f"1 to {SearchSettings.PROXIMITY_MAX_DISTANCE}."
        ),
    ),
) -> None:
    """Set the most words `search --engine proximity` allows between its first and last word.

    `tight` (3 words) finds terms in the same phrase; `medium` (10, the default) in the same
    sentence or clause; `loose` (30) in the same paragraph. A number from 1 to 100 also works.
    """
    storage = open_storage()
    try:
        try:
            SearchSettings.set_proximity_distance(storage, distance)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Search proximity distance set to ", (distance.strip().lower(), Theme.VALUE), "."
            )
        )
    finally:
        storage.close()


@removed_retention_app.command("show")
def removed_retention_show() -> None:
    """Show, in minutes, how long a removed source is kept before it's purged from the DB."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "Removed source retention: ",
                (str(SourceSettings.get_removed_retention_minutes(storage)), Theme.VALUE),
                " minutes",
            )
        )
    finally:
        storage.close()


@removed_retention_app.command("set")
def removed_retention_set(
    minutes: int = typer.Argument(
        ..., help="Minutes to keep a removed source before it's purged from the DB."
    ),
) -> None:
    """Set, in minutes, how long a removed source is kept before it's purged from the DB."""
    storage = open_storage()
    try:
        try:
            SourceSettings.set_removed_retention_minutes(storage, minutes)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Removed source retention set to ", (str(minutes), Theme.VALUE), " minutes."
            )
        )
    finally:
        storage.close()


@retry_app.command("show")
def retry_show() -> None:
    """Show how many times a file's OCR is retried after a transient failure."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "OCR retry attempts: ", (str(OcrSettings.get_retry_attempts(storage)), Theme.VALUE)
            )
        )
    finally:
        storage.close()


@retry_app.command("set")
def retry_set(
    attempts: int = typer.Argument(
        ..., help="Times to retry a file's OCR after a transient failure."
    ),
) -> None:
    """Set how many times a file's OCR is retried after a transient failure."""
    storage = open_storage()
    try:
        try:
            OcrSettings.set_retry_attempts(storage, attempts)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble("OCR retry attempts set to ", (str(attempts), Theme.VALUE), ".")
        )
    finally:
        storage.close()


@stability_check_app.command("show")
def stability_check_show() -> None:
    """Show how long a file must stay unchanged before it's indexed."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "Stability check: ",
                (f"{OcrSettings.get_stability_check_seconds(storage):g}", Theme.VALUE),
                " seconds",
            )
        )
    finally:
        storage.close()


@stability_check_app.command("set")
def stability_check_set(
    seconds: float = typer.Argument(
        ..., help="Seconds between the two checks that a file has stopped changing (0 disables)."
    ),
) -> None:
    """Set how long a file must stay unchanged before it's indexed (0 disables)."""
    storage = open_storage()
    try:
        try:
            OcrSettings.set_stability_check_seconds(storage, seconds)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble("Stability check set to ", (f"{seconds:g}", Theme.VALUE), " seconds.")
        )
    finally:
        storage.close()


@thread_workers_app.command("show")
def thread_workers_show() -> None:
    """Show how many worker threads background indexing uses."""
    storage = open_storage()
    try:
        value = IndexSettings.get_thread_workers(storage)
        label = "disabled (sequential)" if value == "0" else value
        console.print(Text.assemble("Thread workers: ", (label, Theme.VALUE)))
    finally:
        storage.close()


@thread_workers_app.command("set")
def thread_workers_set(
    value: str = typer.Argument(
        ...,
        metavar="VALUE",
        help=(
            f"0 (disable), 1-{IndexSettings.THREAD_WORKERS_MAX}, "
            f"or '{IndexSettings.THREAD_WORKERS_AUTO}'."
        ),
    ),
) -> None:
    """Set how many worker threads background indexing uses."""
    storage = open_storage()
    try:
        try:
            IndexSettings.set_thread_workers(storage, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        label = "disabled (sequential)" if value == "0" else value
        console.print(Text.assemble("Thread workers set to ", (label, Theme.VALUE), "."))
    finally:
        storage.close()


@stale_lock_app.command("show")
def stale_lock_show() -> None:
    """Show whether a stale lock is auto-cleared on the next run."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble("Stale lock: ", (IndexSettings.get_stale_lock(storage), Theme.VALUE))
        )
    finally:
        storage.close()


@stale_lock_app.command("set")
def stale_lock_set(
    value: str = typer.Argument(
        ..., metavar="VALUE", help=f"One of: {', '.join(IndexSettings.STALE_LOCK_VALUES)}."
    ),
) -> None:
    """Set whether a stale lock is auto-cleared on the next run."""
    storage = open_storage()
    try:
        try:
            IndexSettings.set_stale_lock(storage, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Stale lock set to ", (value, Theme.VALUE), "."))
    finally:
        storage.close()


@integrity_check_app.command("show")
def integrity_check_show() -> None:
    """Show whether 'PRAGMA integrity_check' runs automatically when the database is opened."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "Integrity check: ", (DbSettings.get_integrity_check(storage), Theme.VALUE)
            )
        )
    finally:
        storage.close()


@integrity_check_app.command("set")
def integrity_check_set(
    value: str = typer.Argument(
        ..., metavar="VALUE", help=f"One of: {', '.join(DbSettings.INTEGRITY_CHECK_VALUES)}."
    ),
) -> None:
    """Set whether 'PRAGMA integrity_check' runs automatically when the database is opened."""
    storage = open_storage()
    try:
        try:
            DbSettings.set_integrity_check(storage, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Integrity check set to ", (value, Theme.VALUE), "."))
    finally:
        storage.close()


@integrity_check_interval_app.command("show")
def integrity_check_interval_show() -> None:
    """Show, in minutes, how often automatic integrity checks run when 'auto'."""
    storage = open_storage()
    try:
        minutes = DbSettings.get_integrity_check_interval_minutes(storage)
        console.print(
            Text.assemble("Integrity check interval: ", (str(minutes), Theme.VALUE), " minutes")
        )
    finally:
        storage.close()


@integrity_check_interval_app.command("set")
def integrity_check_interval_set(
    minutes: int = typer.Argument(
        ..., help="Minutes between automatic integrity checks when 'auto'."
    ),
) -> None:
    """Set, in minutes, how often automatic integrity checks run when 'auto'."""
    storage = open_storage()
    try:
        try:
            DbSettings.set_integrity_check_interval_minutes(storage, minutes)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Integrity check interval set to ", (str(minutes), Theme.VALUE), " minutes."
            )
        )
    finally:
        storage.close()


@engine_app.command("show")
def engine_show() -> None:
    """Show how thoroughly OCR looks for rotated text."""
    storage = open_storage()
    try:
        console.print(Text.assemble("OCR engine: ", (OcrSettings.get_engine(storage), Theme.VALUE)))
    finally:
        storage.close()


@engine_app.command("set")
def engine_set(
    value: str = typer.Argument(
        ...,
        metavar="VALUE",
        help=(
            f"One of: {', '.join(OcrSettings.ENGINE_MODES)}. quick reads upright text only; "
            "moderate "
            "also reads 90/180/270 degree rotations; deep also reads every 15 degrees. "
            "Files are always indexed quick first, then deeper passes run in the background."
        ),
    ),
) -> None:
    """Set how thoroughly OCR looks for rotated text.

    Every file is indexed quick first so it's searchable right away; moderate
    and deep then add text found in rotated passes while indexing continues.
    Files already indexed are brought up to the new level the next time
    indexing runs.
    """
    storage = open_storage()
    try:
        try:
            OcrSettings.set_engine(storage, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("OCR engine set to ", (value, Theme.VALUE), "."))
    finally:
        storage.close()


@log_level_app.command("show")
def log_level_show() -> None:
    """Show the current log level."""
    storage = open_storage()
    try:
        console.print(Text.assemble("Log level: ", (LogSettings.get_level(storage), Theme.VALUE)))
    finally:
        storage.close()


@log_level_app.command("set")
def log_level_set(
    value: str = typer.Argument(
        ..., metavar="VALUE", help=f"One of: {', '.join(LogSettings.LEVEL_VALUES)}."
    ),
) -> None:
    """Set the log level used for VethuQ's log files (in the logs/ folder)."""
    storage = open_storage()
    try:
        try:
            LogSettings.set_level(storage, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Log level set to ", (value, Theme.VALUE), "."))
    finally:
        storage.close()


@log_retention_app.command("show")
def log_retention_show() -> None:
    """Show how many days of log files are kept."""
    storage = open_storage()
    try:
        console.print(
            Text.assemble(
                "Log retention: ", (f"{LogSettings.get_retention_days(storage)} days", Theme.VALUE)
            )
        )
    finally:
        storage.close()


@log_retention_app.command("set")
def log_retention_set(
    days: int = typer.Argument(..., help="Days of daily log files to keep (at least 1)."),
) -> None:
    """Set how many days of daily log files are kept (older ones are deleted)."""
    storage = open_storage()
    try:
        try:
            LogSettings.set_retention_days(storage, days)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Log retention set to ", (f"{days} days", Theme.VALUE), "."))
    finally:
        storage.close()
