"""Rich rendering of an index run's live state."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn
from rich.progress import TextColumn as ProgressTextColumn
from rich.table import Table
from rich.text import Text
from vethuq_core.index import (
    Eta,
    IndexRunner,
    IndexState,
)
from vethuq_core.ocr import Deepening
from vethuq_core.settings import IndexSettings, OcrSettings
from vethuq_core.source import SourceNotFoundError

from vethuq_cli.console import console


class StatePanel:
    POLL_SECONDS = 1.0
    PHASE_NAMES = {phase: name for name, phase in Deepening.ENGINE_PHASES.items()}
    RUN_STATUS_STYLES = {
        "running": "blue",
        "completed": "green",
        "failed": "red",
        "stopped": "blue",
        "paused": "blue",
    }

    @staticmethod
    def format_duration(seconds: float) -> str:
        minutes, secs = divmod(int(seconds), 60)
        return f"{minutes}m {secs}s" if minutes else f"{secs}s"

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
    def build(conn: sqlite3.Connection, state: IndexState, *, animated: bool) -> Panel:
        status_style = StatePanel.RUN_STATUS_STYLES.get(state.status, "default")

        table = Table.grid(padding=(0, 1))
        table.add_column(style="bright_yellow", no_wrap=True)
        table.add_column()

        table.add_row("Status", Text(state.status, style=f"bold {status_style}"))
        table.add_row("Mode", state.mode)
        table.add_row("Target", state.target or "all sources")

        phase_name = StatePanel.PHASE_NAMES.get(state.phase, str(state.phase))
        max_phase = Deepening.ENGINE_PHASES.get(OcrSettings.get_engine(conn), 1)
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
                    conn, IndexRunner.resolve_targets(conn, state.target), max_phase
                )
            except SourceNotFoundError:
                progress = {}
            for phase, (done, total) in progress.items():
                table.add_row(
                    StatePanel.PHASE_NAMES[phase].capitalize(),
                    StatePanel.progress_cell(done, total, animated),
                )
        else:
            table.add_row("Phase", Text(phase_name))
            table.add_row(
                "Progress",
                StatePanel.progress_cell(state.processed_files, state.total_files, animated),
            )
        failed_style = "bold red" if state.failed_files else "default"
        table.add_row("Failed", Text(str(state.failed_files), style=failed_style))

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

        if state.status == "running":
            by_phase = Eta.phase_seconds(conn, state)
            if by_phase:
                eta = Text(f"~{StatePanel.format_duration(sum(by_phase.values()))}")
                if len(by_phase) > 1:
                    breakdown = " · ".join(
                        f"{StatePanel.PHASE_NAMES[phase]} ~{StatePanel.format_duration(seconds)}"
                        for phase, seconds in sorted(by_phase.items())
                    )
                    eta.append(f"\n{breakdown}", style="bright_black")
                table.add_row("ETA", eta)

        border_style = status_style if status_style != "default" else "white"
        return Panel(table, title="Index Run", border_style=border_style, expand=False)

    @staticmethod
    def print_state(conn: sqlite3.Connection, state: IndexState) -> None:
        console.print(StatePanel.build(conn, state, animated=False))

    @staticmethod
    def live_wait(conn: sqlite3.Connection, pid: int) -> None:
        """Live-refresh the state panel until the run owned by `pid` reaches a terminal state."""
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                time.sleep(StatePanel.POLL_SECONDS)
                state = IndexRunner.read_state()
                if state is not None and state.pid == pid:
                    live.update(StatePanel.build(conn, state, animated=True))
                    if state.status in ("completed", "stopped", "failed"):
                        return
                    continue
                # No state yet for this pid - could just be starting up (the worker
                # hasn't written its first state file yet) or it could genuinely be
                # gone (e.g. crashed before writing anything). Only stop waiting once
                # the process itself is confirmed no longer running.
                running, current_pid = IndexRunner.is_running()
                if not running or current_pid != pid:
                    live.stop()
                    console.print(
                        "Background run ended before reporting any progress. "
                        f"If this is unexpected, check {IndexRunner.log_path()} for errors."
                    )
                    return
