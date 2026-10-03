"""`vethuq settings ...` commands for configuring VethuQ."""

from __future__ import annotations

import typer
from rich.panel import Panel
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


class SettingsPanel:
    @staticmethod
    def build(message: str | Text, title: str, border_style: str) -> Panel:
        """A full-width panel: `message` (white unless already styled), left-aligned `title`,
        coloured border."""
        text = Text(message, style="white") if isinstance(message, str) else message
        # The shared console is soft-wrapping, which would crop long lines in a panel.
        text.no_wrap = False
        text.overflow = "fold"
        return Panel(
            text,
            title=title,
            title_align="left",
            border_style=border_style,
            expand=True,
        )


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
            SettingsPanel.build(
                "GPU enabled. It will be used next time OCR runs, if a CUDA-capable "
                "PaddleOCR build is installed; otherwise CPU is used.",
                "GPU",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@gpu_app.command("disable")
def gpu_disable() -> None:
    """Disable GPU use for OCR (the default) - OCR always runs on CPU."""
    storage = open_storage()
    try:
        GpuSettings.set_enabled(storage, False)
        console.print(
            SettingsPanel.build("GPU disabled. OCR will run on CPU.", "GPU", "bright_black")
        )
    finally:
        storage.close()


@gpu_app.command("status")
def gpu_status() -> None:
    """Show whether GPU use is currently enabled."""
    storage = open_storage()
    try:
        enabled = GpuSettings.is_enabled(storage)
        console.print(
            SettingsPanel.build(
                f"GPU: {'enabled' if enabled else 'disabled'}",
                "GPU",
                "green" if enabled else "bright_black",
            )
        )
    finally:
        storage.close()


@snippet_app.command("show")
def snippet_show() -> None:
    """Show how many characters of context `search` shows around a match."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search snippet context: ", "white"),
                    (str(SearchSettings.get_snippet_context_chars(storage)), Theme.VALUE),
                    (" characters", "white"),
                ),
                "Snippet",
                Theme.PRIMARY,
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
            SettingsPanel.build(
                Text.assemble(
                    ("Search snippet context set to ", "white"),
                    (str(chars), Theme.VALUE),
                    (" characters.", "white"),
                ),
                "Snippet",
                Theme.OK,
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
            SettingsPanel.build(
                Text.assemble(
                    ("Search export format: ", "white"),
                    (SearchSettings.get_export_format(storage), Theme.VALUE),
                ),
                "Export Format",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@export_format_app.command(
    "set",
    help=(
        "Set the default format `search --export` writes to when none is given.\n\n"
        "Formats:\n\n"
        "json - a structured data file (.json) for other tools, scripts or spreadsheets to "
        "read. It records the query, the engine and options used, when it was generated, the "
        "number of results, and every match with its file, page, matched text, surrounding "
        "context and score.\n\n"
        "html - a self-contained web page (.html) to open in a browser and read or share as it "
        "is. It shows the query, the number of results and when it was generated, then each "
        "match with a link to its file, its page and the matched text highlighted in its "
        "context."
    ),
)
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search export format set to ", "white"),
                    (format_, Theme.VALUE),
                    (".", "white"),
                ),
                "Export Format",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@search_engine_app.command("show")
def search_engine_show() -> None:
    """Show the engine `search` uses when `--engine` isn't given."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search engine: ", "white"),
                    (SearchSettings.get_engine(storage), Theme.VALUE),
                ),
                "Search Engine",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@search_engine_app.command(
    "set",
    help=(
        "Set the engine `search` uses when `--engine` isn't given.\n\n"
        "Engines:\n\n"
        "like (the default) - finds your text anywhere, even inside a word, ignoring case "
        'unless case-sensitive. `mus` finds "Museum". Results are ordered by file path.\n\n'
        "lexical - finds your text anywhere, even inside a word, like `like`, but lists the "
        "best-matching pages first. Needs at least 3 characters.\n\n"
        "exact - finds your text exactly as typed: same case, as a whole word. `Museum` "
        'finds "Museum" but not "museum" or "Museums". Always case-sensitive.\n\n'
        "full-text - finds pages containing all your words, in any order, ignoring case and "
        'matching English word forms such as plurals (`museum` finds "Museums"). Quote a '
        '"phrase" to keep words together, end a word with * for a prefix (`mus*`). Best '
        "matches first. Never case-sensitive.\n\n"
        "fuzzy - finds words close to yours, tolerating typos and OCR misreads (`Museurn` "
        "or `Muzeum` for `Museum`). Every word must be matched; how close is set by "
        "`settings search fuzzy threshold`. Closest matches first.\n\n"
        "proximity - finds passages where all your words (two or more, any order) sit within "
        "a set number of words of each other, such as `payment` and `termination` in the same "
        "clause. How near is set by `settings search proximity distance`. One result per "
        "passage, best pages first. Never case-sensitive."
    ),
)
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search engine set to ", "white"),
                    (engine, Theme.VALUE),
                    (".", "white"),
                ),
                "Search Engine",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@case_sensitive_app.command("show")
def case_sensitive_show() -> None:
    """Show whether `search` matches case by default."""
    storage = open_storage()
    try:
        enabled = SearchSettings.is_case_sensitive(storage)
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search case-sensitive: ", "white"),
                    ("enabled" if enabled else "disabled", Theme.VALUE),
                ),
                "Case Sensitive",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@case_sensitive_app.command("enable")
def case_sensitive_enable() -> None:
    """Make `search` match case by default ('like'/'fuzzy'; `--no-case-sensitive` overrides)."""
    storage = open_storage()
    try:
        SearchSettings.set_case_sensitive(storage, True)
        console.print(
            SettingsPanel.build("Search will match case by default.", "Case Sensitive", Theme.OK)
        )
    finally:
        storage.close()


@case_sensitive_app.command("disable")
def case_sensitive_disable() -> None:
    """Make `search` ignore case by default (the default)."""
    storage = open_storage()
    try:
        SearchSettings.set_case_sensitive(storage, False)
        console.print(
            SettingsPanel.build(
                "Search will ignore case by default.", "Case Sensitive", "bright_black"
            )
        )
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
            SettingsPanel.build(
                Text.assemble(
                    ("Search fuzzy threshold: ", "white"),
                    (setting, Theme.VALUE),
                    (f" (similarity {value:.0%})", "white"),
                ),
                "Fuzzy Threshold",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@fuzzy_threshold_app.command(
    "set",
    help=(
        "Set the minimum similarity `search --engine fuzzy` accepts when none is given.\n\n"
        "A word on a page matches one of yours when it is at least this similar: 100% means "
        "identical, and every typo or misread letter lowers it. At most 2 edits are ever "
        "allowed, and words under 4 letters or containing a digit must match exactly.\n\n"
        "Thresholds:\n\n"
        "strict (90%) - finds little beyond plurals and other one-letter variants of longer "
        "words. Fewest false matches.\n\n"
        "balanced (80%, the default) - also catches a typo in a longer word, such as `Musuem` "
        "or `Muzeum` for `Museum`.\n\n"
        "loose (65%) - catches heavier OCR damage such as `Museurn` for `Museum`, with more "
        "noise.\n\n"
        "A percentage (e.g. 75% or 75) or a similarity above 0 and up to 1 (e.g. 0.75) sets "
        "your own level: higher is stricter, lower is looser."
    ),
)
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
    """Set the minimum similarity `search --engine fuzzy` accepts when none is given."""
    storage = open_storage()
    try:
        try:
            SearchSettings.set_fuzzy_threshold(storage, threshold)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search fuzzy threshold set to ", "white"),
                    (threshold.strip().lower(), Theme.VALUE),
                    (".", "white"),
                ),
                "Fuzzy Threshold",
                Theme.OK,
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
            SettingsPanel.build(
                Text.assemble(
                    ("Search proximity distance: ", "white"),
                    (setting, Theme.VALUE),
                    (f" ({value} words)", "white"),
                ),
                "Proximity Distance",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@proximity_distance_app.command(
    "set",
    help=(
        "Set the most words `search --engine proximity` allows between its first and last "
        "word when none is given.\n\n"
        "The distance counts the words that lie between the first and the last of your words "
        "in a passage; any other words of yours in between count too. They may appear in "
        "either order.\n\n"
        "Distances:\n\n"
        "tight (3 words) - your words are practically together, as in the same phrase.\n\n"
        "medium (10 words, the default) - your words are in the same sentence or clause, such "
        "as `payment` and `termination` in one clause of a contract.\n\n"
        "loose (30 words) - your words are in the same paragraph. Finds the most, with more "
        "chance of unrelated matches.\n\n"
        f"A number of words from 1 to {SearchSettings.PROXIMITY_MAX_DISTANCE} sets your own "
        "distance: smaller is stricter, larger is looser. (0 would be an exact phrase - use "
        'the full-text engine with a "quoted phrase" for that.)'
    ),
)
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
    """Set the most words `search --engine proximity` allows between its first and last word."""
    storage = open_storage()
    try:
        try:
            SearchSettings.set_proximity_distance(storage, distance)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Search proximity distance set to ", "white"),
                    (distance.strip().lower(), Theme.VALUE),
                    (".", "white"),
                ),
                "Proximity Distance",
                Theme.OK,
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
            SettingsPanel.build(
                Text.assemble(
                    ("Removed source retention: ", "white"),
                    (str(SourceSettings.get_removed_retention_minutes(storage)), Theme.VALUE),
                    (" minutes", "white"),
                ),
                "Removed Retention",
                Theme.PRIMARY,
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
            SettingsPanel.build(
                Text.assemble(
                    ("Removed source retention set to ", "white"),
                    (str(minutes), Theme.VALUE),
                    (" minutes.", "white"),
                ),
                "Removed Retention",
                Theme.OK,
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
            SettingsPanel.build(
                Text.assemble(
                    ("OCR retry attempts: ", "white"),
                    (str(OcrSettings.get_retry_attempts(storage)), Theme.VALUE),
                ),
                "OCR Retry",
                Theme.PRIMARY,
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
            SettingsPanel.build(
                Text.assemble(
                    ("OCR retry attempts set to ", "white"),
                    (str(attempts), Theme.VALUE),
                    (".", "white"),
                ),
                "OCR Retry",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@stability_check_app.command("show")
def stability_check_show() -> None:
    """Show how long a file must stay unchanged before it's indexed."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Stability check: ", "white"),
                    (f"{OcrSettings.get_stability_check_seconds(storage):g}", Theme.VALUE),
                    (" seconds", "white"),
                ),
                "Stability Check",
                Theme.PRIMARY,
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
            SettingsPanel.build(
                Text.assemble(
                    ("Stability check set to ", "white"),
                    (f"{seconds:g}", Theme.VALUE),
                    (" seconds.", "white"),
                ),
                "Stability Check",
                Theme.OK,
            )
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
        console.print(
            SettingsPanel.build(
                Text.assemble(("Thread workers: ", "white"), (label, Theme.VALUE)),
                "Thread Workers",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@thread_workers_app.command(
    "set",
    help=(
        "Set how many worker threads background indexing uses.\n\n"
        "Each worker reads one file at a time, so more workers index more files in parallel, "
        "at the cost of more CPU and memory.\n\n"
        "Values:\n\n"
        "0 (the default) - disabled: files are indexed one after another on a single thread. "
        "Slowest, but the lightest on your machine.\n\n"
        f"1-{IndexSettings.THREAD_WORKERS_MAX} - a fixed number of workers, used on every run. "
        "A higher number is faster until your CPU or memory runs short.\n\n"
        f"{IndexSettings.THREAD_WORKERS_AUTO} - VethuQ picks the number at the start of each "
        "run from how much CPU and memory is free at that moment."
    ),
)
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Thread workers set to ", "white"),
                    (label, Theme.VALUE),
                    (".", "white"),
                ),
                "Thread Workers",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@stale_lock_app.command("show")
def stale_lock_show() -> None:
    """Show whether a stale lock is auto-cleared on the next run."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Stale lock: ", "white"),
                    (IndexSettings.get_stale_lock(storage), Theme.VALUE),
                ),
                "Stale Lock",
                Theme.PRIMARY,
            )
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Stale lock set to ", "white"),
                    (value, Theme.VALUE),
                    (".", "white"),
                ),
                "Stale Lock",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@integrity_check_app.command("show")
def integrity_check_show() -> None:
    """Show whether 'PRAGMA integrity_check' runs automatically when the database is opened."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Integrity check: ", "white"),
                    (DbSettings.get_integrity_check(storage), Theme.VALUE),
                ),
                "Integrity Check",
                Theme.PRIMARY,
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Integrity check set to ", "white"),
                    (value, Theme.VALUE),
                    (".", "white"),
                ),
                "Integrity Check",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@integrity_check_interval_app.command("show")
def integrity_check_interval_show() -> None:
    """Show, in minutes, how often automatic integrity checks run when 'auto'."""
    storage = open_storage()
    try:
        minutes = DbSettings.get_integrity_check_interval_minutes(storage)
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Integrity check interval: ", "white"),
                    (str(minutes), Theme.VALUE),
                    (" minutes", "white"),
                ),
                "Integrity Check Interval",
                Theme.PRIMARY,
            )
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
            SettingsPanel.build(
                Text.assemble(
                    ("Integrity check interval set to ", "white"),
                    (str(minutes), Theme.VALUE),
                    (" minutes.", "white"),
                ),
                "Integrity Check Interval",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@engine_app.command("show")
def engine_show() -> None:
    """Show how thoroughly OCR looks for rotated text."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("OCR engine: ", "white"), (OcrSettings.get_engine(storage), Theme.VALUE)
                ),
                "OCR Engine",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@engine_app.command(
    "set",
    help=(
        "Set how thoroughly OCR looks for rotated text.\n\n"
        "Every file is indexed quick first so it's searchable right away; moderate and deep "
        "then add text found in rotated passes while indexing continues. Files already indexed "
        "are brought up to the new level the next time indexing runs.\n\n"
        "Values:\n\n"
        "quick (the default) - reads upright text only. The fastest, and enough for most "
        "documents.\n\n"
        "moderate - also reads text rotated by 90, 180 and 270 degrees, such as sideways or "
        "upside-down pages. Slower.\n\n"
        "deep - also reads text at every 15 degrees in between, such as a photo of a page "
        "taken at an angle. The slowest, and the most thorough."
    ),
)
def engine_set(
    value: str = typer.Argument(
        ...,
        metavar="VALUE",
        help=(f"One of: {', '.join(OcrSettings.ENGINE_MODES)}."),
    ),
) -> None:
    """Set how thoroughly OCR looks for rotated text."""
    storage = open_storage()
    try:
        try:
            OcrSettings.set_engine(storage, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("OCR engine set to ", "white"),
                    (value, Theme.VALUE),
                    (".", "white"),
                ),
                "OCR Engine",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@log_level_app.command("show")
def log_level_show() -> None:
    """Show the current log level."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Log level: ", "white"), (LogSettings.get_level(storage), Theme.VALUE)
                ),
                "Log Level",
                Theme.PRIMARY,
            )
        )
    finally:
        storage.close()


@log_level_app.command(
    "set",
    help=(
        "Set the log level used for VethuQ's log files (in the logs/ folder).\n\n"
        "A log file records messages of the chosen level and every more serious one, so "
        "levels further down this list record less.\n\n"
        "Values:\n\n"
        "debug - everything, including fine-grained detail such as each page and rotation "
        "OCR reads. The most verbose; use it when diagnosing a problem. Log files grow "
        "fastest.\n\n"
        "info (the default) - the normal story of a run: startup and shutdown, scans, "
        "indexing progress, plus any warnings and errors.\n\n"
        "warning - only things that went wrong but were handled, such as a retry, and errors.\n\n"
        "error - only failures, such as a file that could not be read or a database error. "
        "The quietest."
    ),
)
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Log level set to ", "white"),
                    (value, Theme.VALUE),
                    (".", "white"),
                ),
                "Log Level",
                Theme.OK,
            )
        )
    finally:
        storage.close()


@log_retention_app.command("show")
def log_retention_show() -> None:
    """Show how many days of log files are kept."""
    storage = open_storage()
    try:
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Log retention: ", "white"),
                    (f"{LogSettings.get_retention_days(storage)} days", Theme.VALUE),
                ),
                "Log Retention",
                Theme.PRIMARY,
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
        console.print(
            SettingsPanel.build(
                Text.assemble(
                    ("Log retention set to ", "white"),
                    (f"{days} days", Theme.VALUE),
                    (".", "white"),
                ),
                "Log Retention",
                Theme.OK,
            )
        )
    finally:
        storage.close()
