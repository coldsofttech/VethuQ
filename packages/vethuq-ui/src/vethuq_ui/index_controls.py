"""Starting, watching and controlling the background index run from the window."""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

from vethuq_core.index import (
    AlreadyRunningError,
    DatabaseIntegrityError,
    Indexing,
    IndexRunner,
    IndexRunnerError,
    IndexState,
    StaleLockError,
)
from vethuq_core.sources import SourceNotFoundError

from vethuq_ui.dialogs import show_error
from vethuq_ui.icons import Icons
from vethuq_ui.ribbon import Ribbon
from vethuq_ui.status_bar import StatusBar


class IndexControls:
    POLL_INTERVAL_MS = 5000
    # With the background service installed the rescan is a queued job rather than a free
    # worker start, so it is asked for less often.
    SERVICE_RESCAN_SECONDS = 60.0

    def __init__(
        self,
        window: tk.Tk,
        db_path: Path | None,
        ribbon: Ribbon,
        status_bar: StatusBar,
        refresh_sources: Callable[[], None],
    ) -> None:
        self._window = window
        self._db_path = db_path
        self._ribbon = ribbon
        self._status_bar = status_bar
        self._refresh_sources = refresh_sources
        self._closing = False
        self._last_queued = 0.0

    def launch_or_attach(self, *, quiet: bool = False) -> None:
        """Start background indexing, unless a run is already in progress.

        `quiet` is for the periodic rescan from `poll`: a failure there is
        swallowed rather than re-shown as a dialog every poll interval.

        A run could already be going if this app instance crashed and
        relaunched, or if `vethuq index run` was started from the CLI - in
        either case we just attach to it via polling rather than starting a
        second one.
        """
        if IndexRunner.is_running(self._db_path)[0]:
            return
        if quiet and Indexing.service_status(self._db_path) is not None:
            now = time.monotonic()
            if now - self._last_queued < self.SERVICE_RESCAN_SECONDS:
                return
            self._last_queued = now
        try:
            Indexing.submit(db_path=self._db_path)
        except (AlreadyRunningError, StaleLockError, SourceNotFoundError):
            # AlreadyRunningError: lost a race with something else starting a
            # run just now - fine, we'll just poll it. StaleLockError: only
            # reachable if the user has set `stale-lock disable`, since the
            # default ("auto") has start_run clear a stale lock itself; leave
            # clearing it to the user (`vethuq index run --force`) rather
            # than doing it silently here. SourceNotFoundError can't actually
            # happen (no target is passed), but is one of start_run's
            # declared errors.
            pass
        except DatabaseIntegrityError as exc:
            if not quiet:
                show_error(self._window, "Database integrity check failed", str(exc))

    def start_polling(self) -> None:
        self._window.after(self.POLL_INTERVAL_MS, self.poll)

    def poll(self) -> None:
        state = IndexRunner.read_state(self._db_path)
        if state is not None and state.is_active:
            self._status_bar.set_indexing(state)
            self._refresh_sources()
        else:
            self._status_bar.set_idle()
            if not self._closing:
                # Nothing running: rescan to pick up new files and sources.
                self.launch_or_attach(quiet=True)
        self.update_buttons(state)
        if not self._closing:
            self._window.after(self.POLL_INTERVAL_MS, self.poll)

    def shutdown(self) -> None:
        # Signal only - don't wait. The worker finishes whatever file it's
        # on and exits by itself (cleaning up its own lock/control files and
        # index_runs row), so the app doesn't need to stay open to see that
        # happen.
        self._closing = True
        if Indexing.service_status(self._db_path) is not None:
            # The service keeps indexing after the window closes; that is what it is for.
            return
        try:
            IndexRunner.signal_stop(db_path=self._db_path)
        except IndexRunnerError:
            pass

    def start_targeted_run(self, source_id: str, *, restart: bool) -> None:
        try:
            Indexing.submit(source_id, restart=restart, db_path=self._db_path)
        except (
            AlreadyRunningError,
            StaleLockError,
            DatabaseIntegrityError,
            SourceNotFoundError,
        ) as exc:
            show_error(self._window, "Could not start indexing", str(exc))
        except IndexRunnerError as exc:
            show_error(self._window, "Could not start indexing", str(exc))
        else:
            self._refresh_sources()

    def stop(self) -> None:
        try:
            IndexRunner.signal_stop(db_path=self._db_path)
        except IndexRunnerError as exc:
            show_error(self._window, "Could not stop indexing", str(exc))

    def toggle_pause_resume(self) -> None:
        state = IndexRunner.read_state(self._db_path)
        try:
            if state is not None and state.is_paused:
                IndexRunner.request_resume(db_path=self._db_path)
            else:
                IndexRunner.request_pause(db_path=self._db_path)
        except IndexRunnerError as exc:
            show_error(self._window, "Could not update index run", str(exc))

    def update_buttons(self, state: IndexState | None) -> None:
        running = state is not None and state.is_active
        paused = state is not None and state.is_paused
        icon = Icons.get("resume" if paused else "pause")
        if icon is not None:
            self._ribbon.pause_resume_button.config(image=icon)
        self._ribbon.pause_resume_button.config(
            text="Resume" if paused else "Pause",
            state=tk.NORMAL if running else tk.DISABLED,
        )
        self._ribbon.stop_button.config(state=tk.NORMAL if running else tk.DISABLED)
