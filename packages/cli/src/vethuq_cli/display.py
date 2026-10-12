"""Rich panels for search results, an index run and statistics (plain text and tables under
`--json`/`--export` are handled by the callers)."""

from __future__ import annotations

from itertools import groupby

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from vethuq.formatting import Formatting
from vethuq_cli.output import cell, plain

PRIMARY = "cyan"
ACCENTS = ("cyan", "magenta")
STATUS_STYLES = {
    "running": "cyan",
    "completed": "green",
    "failed": "red",
    "stopped": "cyan",
    "paused": "yellow",
}


def _text(value: str, style: str = "white") -> Text:
    return Text(value, style=style, no_wrap=False, overflow="fold")


def message_panel(message: str, border: str, title: str) -> Panel:
    return Panel(_text(message), title=title, title_align="left", border_style=border, expand=True)


# ----- search -----------------------------------------------------------------------------------


def _snippet(match, accent: str) -> Panel:
    snippet = Text(no_wrap=False, overflow="fold")
    snippet.append(("..." if match.truncated_before else "") + match.before)
    snippet.append(match.matched, style=f"bold black on {accent}")
    snippet.append(match.after + ("..." if match.truncated_after else ""))
    return Panel(snippet, border_style=accent, expand=True)


def _label(match, accent: str) -> Text:
    label = Text(style=accent, no_wrap=False, overflow="fold")
    label.append(f"Page: {match.page_number} of {match.total_pages} [{match.source}]")
    label.append(f" [{match.engine}]", style=f"bold {accent}")
    if match.score is not None and match.engine in ("fuzzy", "noise-fuzzy", "semantic"):
        label.append(f" {match.score:.0%}")
    also = [e for e in match.matched_by if e != match.engine]
    if also:
        label.append("  also: " + ", ".join(also), style="bright_black")
    if match.modifiers:
        label.append("  · " + ", ".join(match.modifiers), style="bright_black")
    return label


def search_panel(result, offset: int = 0) -> Panel:
    """One panel per file, each match a labelled snippet box."""
    word = "match" if result.total == 1 else "matches"
    title = f"Search Results: {result.total} {word} (engine: {result.engine})"
    if not result.matches:
        return Panel(
            _text("No matches."),
            title=title,
            title_align="left",
            border_style="yellow",
            expand=True,
        )
    files: list[RenderableType] = []
    for number, (_, group) in enumerate(groupby(result.matches, key=lambda m: m.file_id)):
        matches = list(group)
        first, accent = matches[0], ACCENTS[number % len(ACCENTS)]
        path = f"File: {first.file_path}"
        if first.duplicate_of_path:
            path += f"  (duplicate of {first.duplicate_of_path})"
        entries: list[RenderableType] = [_text(path, f"bold {accent}")]
        for match in matches:
            entries += [_label(match, accent), _snippet(match, accent)]
        files.append(
            Panel(
                Group(*entries),
                title=Text(first.file_name, style=f"bold {accent}"),
                title_align="left",
                border_style=accent,
                expand=True,
            )
        )
    return Panel(
        Group(*files),
        title=Text(title, style="bold"),
        title_align="left",
        border_style=PRIMARY,
        expand=True,
    )


# ----- index ------------------------------------------------------------------------------------


def _progress(done: int, total: int, animated: bool) -> RenderableType:
    if not animated:
        percent = done / total * 100 if total else 100.0
        return f"{done}/{total} ({percent:.0f}%)"
    bar = Progress(
        BarColumn(bar_width=30), TextColumn("{task.completed}/{task.total}"), TaskProgressColumn()
    )
    bar.add_task("progress", total=total or 1, completed=done)
    return bar


def index_panel(status, *, animated: bool = False) -> Panel:
    run = status.run
    state = "paused" if status.paused else "stopping" if status.stopping else plain(run.status)
    style = STATUS_STYLES.get(plain(run.status), "white")
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style=PRIMARY, no_wrap=True)
    grid.add_column()
    grid.add_row(
        "Status", Text(state + (" (stalled)" if status.stalled else ""), style=f"bold {style}")
    )
    grid.add_row("Mode", run.mode)
    grid.add_row("Target", run.target or "all sources")
    grid.add_row("Phase", status.phase or "-")
    grid.add_row("Progress", _progress(run.files_processed, run.files_total, animated))
    grid.add_row("Pages", f"{run.pages_processed} ({run.ocr_pages} by OCR)")
    grid.add_row(
        "Failed", Text(str(run.files_failed), style="red" if run.files_failed else "white")
    )
    if status.unsupported_files:
        grid.add_row("Unsupported", str(status.unsupported_files))
    grid.add_row("Workers", f"{status.workers_active} active of {run.workers}")
    if status.current_files:
        names = "\n".join(
            f"• {f.replace(chr(92), '/').rsplit('/', 1)[-1]}" for f in status.current_files
        )
        grid.add_row(
            "Current files" if len(status.current_files) > 1 else "Current file", Text(names)
        )
    if run.error:
        grid.add_row("Error", Text(run.error, style="red"))
    if status.stalled:
        grid.add_row(
            "Warning", Text("No sign of life for a while - the worker may be hung.", style="yellow")
        )
    if plain(run.status) == "running" and status.eta.seconds:
        eta = Text(f"~{Formatting.duration(status.eta.seconds)}")
        if not status.eta.complete:
            eta.append("  (part of the work has no history)", style="bright_black")
        grid.add_row("ETA", eta)
    return Panel(grid, title="Index Run", title_align="left", border_style=style, expand=True)


# ----- stats ------------------------------------------------------------------------------------


def stats_panel(overview) -> Panel:
    table = Table(box=box.SIMPLE, header_style=f"bold {PRIMARY}", border_style=PRIMARY)
    table.add_column(overview.group_by.value.replace("_", " ").capitalize())
    for name in ("Files", "Pages", "Native", "OCR", "Confidence", "Pages/min", "Credits"):
        table.add_column(name, justify="right")

    def add(row, bold: bool = False, label: str | None = None) -> None:
        confidence = f"{row.confidence:.0%}" if row.confidence is not None else "-"
        speed = cell(round(row.pages_per_minute, 1)) if row.pages_per_minute else "-"
        table.add_row(
            label or row.key,
            cell(row.files),
            str(row.pages),
            str(row.native_pages),
            str(row.ocr_pages),
            confidence,
            speed,
            f"{row.credits:g}",
            style="bold" if bold else None,
        )

    for row in overview.rows:
        add(row)
    table.add_section()
    add(overview.total, bold=True, label="Total")
    return Panel(table, title="Statistics", title_align="left", border_style=PRIMARY, expand=True)
