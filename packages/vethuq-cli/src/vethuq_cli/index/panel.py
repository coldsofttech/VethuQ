"""Rich rendering of an index run's live state."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich import box
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn
from rich.progress import TextColumn as ProgressTextColumn
from rich.table import Table
from rich.text import Text
from vethuq_core.formatting import Formatting
from vethuq_core.index import (
    Eta,
    IndexRunner,
    IndexRunnerError,
    IndexState,
)
from vethuq_core.ocr import Deepening
from vethuq_core.settings import IndexSettings
from vethuq_core.sources import SourceNotFoundError
from vethuq_core.storage import Storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme


class IndexPanel:
    @staticmethod
    def message(message: str | Text, border_style: str, title: str = "Index") -> Panel:
        """A full-width panel: `message` (white unless already styled), left-aligned `title`,
        coloured border."""
        text = Text(message, style="white") if isinstance(message, str) else message
        # The shared console is soft-wrapping, which would crop long lines in a panel.
        text.no_wrap = False
        text.overflow = "fold"
        return Panel(text, title=title, title_align="left", border_style=border_style, expand=True)

    @staticmethod
    def table(table: Table, title: str, border_style: str = Theme.PRIMARY) -> Panel:
        """A full-width panel around `table`, with a left-aligned `title`."""
        return Panel(table, title=title, title_align="left", border_style=border_style, expand=True)

    @staticmethod
    def friendly_time(value: str, now: datetime | None = None) -> str:
        """An ISO timestamp as a short, local-time phrase: "Today, 13:40", "Yesterday, 09:12",
        "3 Oct, 13:40" (this year) or "3 Oct 2025, 13:40". `value` unchanged if it isn't ISO."""
        try:
            moment = datetime.fromisoformat(value).astimezone()
        except ValueError:
            return value
        current = (now or datetime.now().astimezone()).astimezone()
        clock = moment.strftime("%H:%M")
        days_ago = (current.date() - moment.date()).days
        if days_ago == 0:
            return f"Today, {clock}"
        if days_ago == 1:
            return f"Yesterday, {clock}"
        if moment.year == current.year:
            return f"{moment.day} {moment.strftime('%b')}, {clock}"
        return f"{moment.day} {moment.strftime('%b %Y')}, {clock}"

    @staticmethod
    def new_table() -> Table:
        """A table in the style the other panels use."""
        return Table(
            box=box.SIMPLE, header_style=f"bold {Theme.PRIMARY}", border_style=Theme.PRIMARY
        )


class StatePanel:
    RUN_STATUS_STYLES = {
        "running": Theme.PRIMARY,
        "completed": Theme.SUCCESS,
        "failed": Theme.DANGER,
        "stopped": Theme.PRIMARY,
        "paused": Theme.WARNING,
    }

    @staticmethod
    def progress_bar(processed: int, total: int) -> Progress:
        """A `Progress` renderable showing an animated bar plus count and percentage.

        Not started (`.start()` is never called) - it's rendered as a plain,
        self-contained renderable, either once for a static snapshot or repeatedly
        via `Live.update()`, without spinning up its own refresh thread.
        """
        bar = Progress(
            BarColumn(bar_width=30),
            ProgressTextColumn("{task.completed}/{task.total}"),
            TaskProgressColumn(),
        )
        bar.add_task("progress", total=total or 1, completed=processed)
        return bar

    @staticmethod
    def progress_cell(done: int, total: int, animated: bool) -> Progress | str:
        if animated:
            return StatePanel.progress_bar(done, total)
        percent = (done / total * 100) if total else 100.0
        return f"{done}/{total} ({percent:.0f}%)"

    @staticmethod
    def build(storage: Storage, state: IndexState, *, animated: bool) -> Panel:
        status_style = StatePanel.RUN_STATUS_STYLES.get(state.status, "default")

        table = Table.grid(padding=(0, 1))
        table.add_column(style=Theme.LABEL, no_wrap=True)
        table.add_column()

        table.add_row("Status", Text(state.status, style=f"bold {status_style}"))
        table.add_row("Mode", state.mode)
        table.add_row("Target", state.target or "all sources")

        phase_name = Deepening.PHASE_NAMES.get(state.phase, str(state.phase))
        max_phase = Deepening.max_phase(storage)
        if max_phase > 1:
            table.add_row("Phase", Text(f"{phase_name} ({state.phase}/{max_phase})", style="bold"))
            # Quick counts files; the deeper phases count pages - each shows how much of
            # what it applies to has been through it.
            table.add_row(
                "Quick",
                StatePanel.progress_cell(state.processed_files, state.total_files, animated),
            )
            try:
                progress = Deepening.progress(
                    storage, IndexRunner.resolve_targets(storage, state.target), max_phase
                )
            except SourceNotFoundError:
                progress = {}
            for phase, (done, total) in progress.items():
                table.add_row(
                    Deepening.PHASE_NAMES[phase].capitalize(),
                    StatePanel.progress_cell(done, total, animated),
                )
        else:
            table.add_row("Phase", Text(phase_name))
            table.add_row(
                "Progress",
                StatePanel.progress_cell(state.processed_files, state.total_files, animated),
            )
        failed_style = Theme.ERROR if state.failed_files else "default"
        table.add_row("Failed", Text(str(state.failed_files), style=failed_style))
        table.add_row("Unsupported", Text(str(state.unsupported_files)))

        if state.thread_workers_setting == "0":
            workers_label = "disabled (sequential)"
        elif state.thread_workers_setting == IndexSettings.THREAD_WORKERS_AUTO:
            thread_word = "thread" if state.workers == 1 else "threads"
            workers_label = f"auto (currently {state.workers} {thread_word})"
        else:
            workers_label = f"{state.workers} threads"
        table.add_row("Workers", workers_label)

        if state.current_files:
            label = "Current files" if len(state.current_files) > 1 else "Current file"
            files_text = Text("\n".join(f"• {Path(f).name}" for f in state.current_files))
            table.add_row(label, files_text)

        if state.error:
            table.add_row("Error", Text(state.error, style=Theme.ERROR))
        if IndexRunner.is_stalled(state):
            stalled = Formatting.duration(state.heartbeat_age_seconds)
            table.add_row(
                "Warning",
                Text(
                    f"No sign of life for {stalled} - the worker may be hung.",
                    style=Theme.WARNING,
                ),
            )

        if state.status == "running":
            by_phase = Eta.phase_seconds(storage, state)
            if by_phase:
                eta = Text(f"~{Formatting.duration(sum(by_phase.values()))}")
                if len(by_phase) > 1:
                    breakdown = " · ".join(
                        f"{Deepening.PHASE_NAMES[phase]} ~{Formatting.duration(seconds)}"
                        for phase, seconds in sorted(by_phase.items())
                    )
                    eta.append(f"\n{breakdown}", style="bright_black")
                table.add_row("ETA", eta)

        border_style = status_style if status_style != "default" else "white"
        return Panel(
            table,
            title="Index Run",
            title_align="left",
            border_style=border_style,
            expand=True,
        )

    @staticmethod
    def print_state(storage: Storage, state: IndexState) -> None:
        console.print(StatePanel.build(storage, state, animated=False))

    @staticmethod
    def live_wait_or_stop(storage: Storage, pid: int) -> bool:
        """Like `live_wait`, but Ctrl+C stops the run this command started.

        Returns True if the user interrupted (the run was asked to stop).
        """
        try:
            StatePanel.live_wait(storage, pid)
        except KeyboardInterrupt:
            try:
                IndexRunner.request_stop()
            except IndexRunnerError as exc:
                error_console.print(str(exc), style=Theme.ERROR)
            else:
                console.print(
                    IndexPanel.message(
                        "Interrupted - index run stopped.", Theme.WARNING, "Index Run"
                    )
                )
            return True
        return False

    @staticmethod
    def live_wait(storage: Storage, pid: int) -> None:
        """Live-refresh the state panel until the run owned by `pid` reaches a terminal state."""
        with Live(console=console, refresh_per_second=4) as live:
            final = IndexRunner.wait(
                pid, lambda state: live.update(StatePanel.build(storage, state, animated=True))
            )
        if final is None or final.pid != pid:
            console.print(
                IndexPanel.message(
                    "Background run ended before reporting any progress. "
                    f"If this is unexpected, check {IndexRunner.log_path()} for errors.",
                    Theme.WARNING,
                    "Index Run",
                )
            )
