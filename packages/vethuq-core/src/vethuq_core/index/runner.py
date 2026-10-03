"""Background OCR indexing runs: launch, track progress, and control them.

`vethuq index run` launches OCR indexing as a detached subprocess so the CLI
returns immediately; `_run_worker` below is what that subprocess executes.
Live progress is tracked in a small JSON state file plus a PID lock file next
to the database - not in the database itself, to avoid write contention with
the OCR indexing writes already happening there. Once a run ends, its summary
is recorded in the `index_runs` table so `vethuq index history` can list past
runs after the state file has been overwritten by a later one.

The state file is written only by the worker and the control file only by the
CLI (`request_stop`/`request_pause`/`request_resume`) - keeping them separate
means neither writer can clobber the other's most recent update, which a
single shared file could not guarantee (the worker persists its whole state
after every file, which would silently overwrite a control change written in
between).
"""

from __future__ import annotations

import faulthandler
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from vethuq_core.logs import Logs
from vethuq_core.ocr import Ocr, Pending, Scheduler
from vethuq_core.paths import Paths
from vethuq_core.readers import Readers
from vethuq_core.settings import IndexSettings, OcrSettings
from vethuq_core.sources import Source, Sources
from vethuq_core.storage import Row, Storage, default_db_path, open_storage


class IndexRunnerError(Exception):
    """Base class for index-runner errors."""


class AlreadyRunningError(IndexRunnerError):
    """A background index run is already active."""


class StaleLockError(IndexRunnerError):
    """A lock file exists but its process is no longer running."""


@dataclass
class IndexState:
    run_id: int
    pid: int
    target: str | None
    mode: str  # "run" | "restart"
    status: str  # "running" | "paused" | "completed" | "stopped" | "failed"
    total_files: int
    processed_files: int
    failed_files: int
    thread_workers_setting: str  # raw `thread_workers` setting for this run: "0" | "1"-"8" | "auto"
    workers: int  # current effective worker count (see Scheduler.resolve_workers) - live for "auto"
    current_files: list[str]  # files each active worker is on right now (0-N of them)
    started_at: str
    updated_at: str
    # What the run is on: 1 while files get their quick first pass, then the
    # phase (2/3) of the deeper page pass in progress. `engine` is the
    # `index_engine` setting the run started with; `deepened_pages` counts pages
    # that finished a deeper phase. Defaulted so a state file from before
    # phases existed still loads.
    engine: str = "quick"
    phase: int = 1
    deepened_pages: int = 0
    # Why a run ended as "failed" when the worker couldn't say so itself (it died).
    error: str | None = None

    @property
    def heartbeat_age_seconds(self) -> float:
        """Seconds since the worker last refreshed this state (see `IndexRunner._Heartbeat`)."""
        updated = datetime.fromisoformat(self.updated_at)
        return (datetime.now(UTC) - updated).total_seconds()

    @property
    def is_active(self) -> bool:
        """The run is still going (running or paused)."""
        return self.status in ("running", "paused")

    @property
    def is_paused(self) -> bool:
        return self.status == "paused"

    @property
    def is_finished(self) -> bool:
        """The run has ended, one way or another."""
        return self.status in ("completed", "stopped", "failed")

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> IndexState:
        return cls(**json.loads(text))


@dataclass
class IndexRun:
    id: int
    target: str | None
    mode: str  # "run" | "restart"
    status: str  # "running" | "completed" | "stopped" | "failed"
    pid: int | None
    total_files: int
    processed_files: int
    failed_files: int
    workers: int | None
    started_at: str
    completed_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def _from_row(cls, row: Row) -> IndexRun:
        return cls(
            id=row["id"],
            target=row["target"],
            mode=row["mode"],
            status=row["status"],
            pid=row["pid"],
            total_files=row["total_files"],
            processed_files=row["processed_files"],
            failed_files=row["failed_files"],
            workers=row["workers"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )


class IndexRunner:
    _STATE_FILENAME = "index_state.json"
    _CONTROL_FILENAME = "index.control"
    _LOCK_FILENAME = "index.lock"
    _logger = Logs.get_logger("index")
    _STOP_TIMEOUT_SECONDS = 5.0
    _PAUSE_POLL_SECONDS = 1.0
    _INTERRUPTED_MESSAGE = "Interrupted: a previous index run did not finish cleanly."
    _DIED_MESSAGE = (
        "The index worker exited unexpectedly; see the index log for the last thing it did."
    )
    # Where the worker's `faulthandler` writes the Python stack if the process dies on a native
    # fault (an access violation inside an OCR library, say) - nothing else survives that.
    _CRASH_FILENAME = "index.crash.log"
    # The worker refreshes its state this often even while it's busy on one long file, so a
    # state that has gone quiet for `STALE_HEARTBEAT_SECONDS` (well over a heartbeat, in case
    # a native OCR call holds the interpreter for a while) belongs to a worker that is hung.
    HEARTBEAT_SECONDS = 5.0
    STALE_HEARTBEAT_SECONDS = 120.0
    # Bundled next to the desktop/CLI exes by the installer build. A frozen exe
    # can't be asked to run `-m vethuq_core.index.runner` (it would just start
    # the app again), so frozen builds spawn this dedicated worker exe instead.
    _WORKER_EXE_NAME = "vethuq-worker.exe"

    @staticmethod
    def _state_path(db_path: Path) -> Path:
        return Paths.run_dir(db_path) / IndexRunner._STATE_FILENAME

    @staticmethod
    def _control_path(db_path: Path) -> Path:
        return Paths.run_dir(db_path) / IndexRunner._CONTROL_FILENAME

    @staticmethod
    def _lock_path(db_path: Path) -> Path:
        return Paths.run_dir(db_path) / IndexRunner._LOCK_FILENAME

    @staticmethod
    def log_path(db_path: Path | None = None) -> Path:
        """Path to the index log (`index.log`), which records runs, worker threads and crashes."""
        return Paths.logs_dir(db_path or default_db_path()) / Logs.COMPONENTS["index"]

    @staticmethod
    def crash_log_path(db_path: Path | None = None) -> Path:
        """Path to the worker's crash trace (`index.crash.log`); empty unless it died hard."""
        return Paths.logs_dir(db_path or default_db_path()) / IndexRunner._CRASH_FILENAME

    @staticmethod
    def _enable_crash_trace(db_path: Path) -> IO[str] | None:
        """Point `faulthandler` at the crash trace file for this worker; returns the open file.

        The file is kept open for the worker's whole life (faulthandler writes through its
        descriptor from the fault handler itself). A trace left by an earlier worker that nobody
        has reported yet is moved into the index log first. Never raises: without a trace file the
        worker simply runs as before.
        """
        IndexRunner._collect_crash_trace(db_path)
        try:
            handle = open(IndexRunner.crash_log_path(db_path), "w", encoding="utf-8")  # noqa: SIM115
            faulthandler.enable(file=handle, all_threads=True)
        except (OSError, RuntimeError):
            IndexRunner._logger.warning("Could not enable the crash trace", exc_info=True)
            return None
        return handle

    @staticmethod
    def _disable_crash_trace(db_path: Path, handle: IO[str] | None) -> None:
        """Stop tracing and tidy up: a trace file that stayed empty means a clean exit."""
        if handle is None:
            return
        faulthandler.disable()
        handle.close()
        path = IndexRunner.crash_log_path(db_path)
        try:
            if path.stat().st_size == 0:
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def _collect_crash_trace(db_path: Path) -> str | None:
        """Move a crash trace left by a dead worker into the index log; return its first line.

        Returns None (and leaves nothing behind) when there is no trace. The trace holds only
        Python frames - file paths, line numbers and function names - never document text.
        """
        path = IndexRunner.crash_log_path(db_path)
        try:
            trace = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if not trace:
            path.unlink(missing_ok=True)
            return None
        IndexRunner._logger.error("The index worker died on a fault; its trace follows:\n%s", trace)
        path.unlink(missing_ok=True)
        return trace.splitlines()[0].strip()

    class _Heartbeat:
        """Refreshes the state file's `updated_at` on a timer while the worker runs.

        Progress is only written when a file or page starts or finishes, so a long
        OCR pass would otherwise look the same as a worker that has hung. Shares the
        worker's `state_lock`, so a refresh never interleaves with a progress write.
        """

        def __init__(self, db_path: Path, state: IndexState, state_lock: threading.Lock) -> None:
            self._db_path = db_path
            self._state = state
            self._state_lock = state_lock
            self._stopped = threading.Event()
            self._thread = threading.Thread(target=self._beat, name="index-heartbeat", daemon=True)

        def start(self) -> None:
            self._thread.start()

        def stop(self) -> None:
            """Stop refreshing and wait for any refresh in flight; safe to call twice."""
            self._stopped.set()
            if self._thread.is_alive():
                self._thread.join(timeout=IndexRunner.HEARTBEAT_SECONDS)

        def _beat(self) -> None:
            while not self._stopped.wait(IndexRunner.HEARTBEAT_SECONDS):
                with self._state_lock:
                    if self._stopped.is_set():
                        return
                    try:
                        IndexRunner._write_state(self._db_path, self._state)
                    except OSError:
                        IndexRunner._logger.warning("Could not refresh the index heartbeat")

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        # Unique per writer: the heartbeat thread and the main thread can write at once.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if sys.platform == "win32":
            # A direct WinAPI call, not a `tasklist` subprocess: spawning a new
            # process just to check another one's liveness is slow (tens to
            # hundreds of ms, worse under antivirus real-time scanning of new
            # process launches) and this is called from places - the desktop
            # app's launch/add-source/close paths - where that's felt as a
            # visible stutter or freeze.
            import ctypes

            still_active = 259
            query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(query_limited_information, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _force_kill(pid: int) -> None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
            )
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def read_state(db_path: Path | None = None, *, raw: bool = False) -> IndexState | None:
        """Return the most recent run's live/last-known state, if one exists.

        The state file isn't durable history (that's `index_runs`) - it's just
        scratch progress for the current/last run - so a file left behind by an
        older version of this code, in a since-changed format, is treated the
        same as no state at all rather than raised as an error.

        A worker that died without recording its end (a crash, a kill) leaves its
        state saying "running" forever, so unless `raw` is True a state that claims
        to be active is checked against the worker's process: if nothing is alive
        behind it, the run is recorded as failed (here and in `index history`) and
        returned as such. `raw` returns the file as written, for the code that does
        its own reconciling.
        """
        db_path = db_path or default_db_path()
        path = IndexRunner._state_path(db_path)
        if not path.exists():
            return None
        try:
            state = IndexState.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError):
            return None
        if not raw and state.is_active and not IndexRunner._worker_alive(db_path, state):
            IndexRunner._record_died(db_path, state)
        return state

    @staticmethod
    def _worker_alive(db_path: Path, state: IndexState) -> bool:
        """Whether a process is still behind `state` - the locked launcher or the worker itself.

        The lock holds the pid the launcher spawned, which can differ from the worker's own
        (`state.pid`) when the launcher is a shim, so either one being alive counts.
        """
        locked, _ = IndexRunner.is_running(db_path)
        return locked or IndexRunner._is_pid_running(state.pid)

    @staticmethod
    def _record_died(db_path: Path, state: IndexState) -> None:
        """Mark the run behind a dead worker as failed, in `state` and on disk.

        The stale lock is left in place: `start_run` clears it on the next run, which also
        resets any file the dead worker left claimed.
        """
        # Read-only callers (`index status`) haven't set the index log up, and this is a fact
        # the log should hold.
        Logs.setup("index", db_path)
        IndexRunner._logger.warning(
            "Index run %d (worker pid=%d) is gone without having finished; marking it failed",
            state.run_id,
            state.pid,
        )
        fault = IndexRunner._collect_crash_trace(db_path)
        state.error = (
            f"The index worker crashed ({fault}); the fault trace is in the index log."
            if fault
            else IndexRunner._DIED_MESSAGE
        )
        state.current_files = []
        try:
            IndexRunner._mark_run_ended(db_path, state, "failed")
        except Exception:  # noqa: BLE001 - reporting must not fail because bookkeeping did
            IndexRunner._logger.exception("Could not record the dead index run %d", state.run_id)
            state.status = "failed"

    @staticmethod
    def is_stalled(state: IndexState) -> bool:
        """Whether an active run's worker is alive but has stopped refreshing its state (hung)."""
        return state.is_active and state.heartbeat_age_seconds > IndexRunner.STALE_HEARTBEAT_SECONDS

    @staticmethod
    def _write_state(db_path: Path, state: IndexState) -> None:
        state.updated_at = datetime.now(UTC).isoformat()
        IndexRunner._atomic_write(IndexRunner._state_path(db_path), state.to_json())

    @staticmethod
    def _read_control(db_path: Path) -> str:
        path = IndexRunner._control_path(db_path)
        if not path.exists():
            return "run"
        return path.read_text(encoding="utf-8").strip() or "run"

    @staticmethod
    def _set_control(db_path: Path, control: str) -> None:
        IndexRunner._atomic_write(IndexRunner._control_path(db_path), control)

    @staticmethod
    def is_running(db_path: Path | None = None) -> tuple[bool, int | None]:
        """Return (running, pid). `running` is False if the lock is stale."""
        lock_path = IndexRunner._lock_path(db_path or default_db_path())
        if not lock_path.exists():
            return False, None
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip())
        except ValueError:
            return False, None
        return IndexRunner._is_pid_running(pid), pid

    @staticmethod
    def _worker_command(db_path: Path, target: str | None, restart: bool) -> list[str]:
        args = [str(db_path), target or "", "restart" if restart else "run"]
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name(IndexRunner._WORKER_EXE_NAME)
            if not worker.exists():
                raise IndexRunnerError(f"index worker not found at {worker}")
            return [str(worker), *args]
        return [sys.executable, "-m", "vethuq_core.index.runner", *args]

    @staticmethod
    def start_run(
        target: str | None = None,
        *,
        force: bool = False,
        restart: bool = False,
        db_path: Path | None = None,
    ) -> int:
        """Launch OCR indexing as a detached background process. Returns its pid.

        When `restart` is True, only files that previously failed are retried
        (see `Quick.run`'s `only_failed`); otherwise new and previously-failed
        files are processed as usual.
        """
        db_path = db_path or default_db_path()
        Logs.setup("index", db_path)
        running, pid = IndexRunner.is_running(db_path)
        if running:
            raise AlreadyRunningError(f"An index run is already in progress (pid {pid}).")

        lock_path = IndexRunner._lock_path(db_path)
        if lock_path.exists():
            if not force:
                storage = open_storage(db_path)
                try:
                    auto_clear = IndexSettings.get_stale_lock(storage) != "disable"
                finally:
                    storage.close()
                if not auto_clear:
                    raise StaleLockError(
                        "Found a lock left behind by a run that didn't exit cleanly. "
                        "Use --force to clear it and start a new run, or "
                        "`vethuq settings index stale-lock set enable` to clear it "
                        "automatically next time."
                    )
            lock_path.unlink(missing_ok=True)
            IndexRunner._logger.warning(
                "Cleared stale index lock; reconciling the run that left it"
            )
            IndexRunner._reconcile_orphaned_run(db_path)

        storage = open_storage(db_path)
        try:
            if target is not None:
                # raises SourceNotFoundError if invalid
                Sources.get(storage, Sources.coerce(target))
        finally:
            storage.close()

        IndexRunner._set_control(db_path, "run")
        mode_name = "restart" if restart else "run"

        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NO_WINDOW suppresses the console window a console-subsystem
            # child (python.exe) would otherwise pop up; CREATE_NEW_PROCESS_GROUP
            # keeps it from receiving Ctrl+C aimed at the parent's console.
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        # The worker logs to `index.log` itself (see `main`), including a crash's
        # traceback, so its stdout/stderr aren't needed.
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
            IndexRunner._worker_command(db_path, target, restart),
            # Stops a onefile-frozen parent's bundle env from leaking into
            # the (also onefile) worker exe, which must unpack its own.
            env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(sys.platform != "win32"),
            creationflags=creationflags,
        )
        IndexRunner._logger.info(
            "Started index worker pid=%d mode=%s target=%s", process.pid, mode_name, target or "all"
        )
        IndexRunner._atomic_write(lock_path, str(process.pid))
        return process.pid

    @staticmethod
    def _reclaim_stuck_processing(db_path: Path) -> None:
        """Reset every `document_index` row a run's claim left at status='processing'
        back to 'error', so it's retried instead of permanently blocking any future
        claim of that row (see `Document.upsert`).

        Only safe to call once nothing is still actively working on those rows -
        after a crash is reconciled at the next run's startup, or right after
        force-killing a run that missed its stop timeout.
        """
        storage = open_storage(db_path)
        try:
            storage.fail_stuck_processing_document_index(
                IndexRunner._INTERRUPTED_MESSAGE, datetime.now(UTC).isoformat()
            )
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def _reconcile_orphaned_run(db_path: Path) -> None:
        """Mark the bookkeeping left by a run that didn't exit cleanly as failed.

        Called right after clearing a stale lock, so `index status`/`index history`
        and the desktop app stop showing a run as still "running" once it's known
        the process behind it is gone. Also resets any `document_index` row that
        run left claimed ('processing') - reachable only here, since it's the
        point where it's confirmed nothing is still working on it - so it's
        retried on the next run instead of its claim blocking it forever.
        """
        state = IndexRunner.read_state(db_path, raw=True)
        if state is not None and state.is_active:
            IndexRunner._mark_run_ended(db_path, state, "failed")
        else:
            storage = open_storage(db_path)
            try:
                storage.fail_all_running_index_runs(datetime.now(UTC).isoformat())
                storage.commit()
            finally:
                storage.close()
        IndexRunner._reclaim_stuck_processing(db_path)

    @staticmethod
    def _mark_run_ended(db_path: Path, state: IndexState, status: str) -> None:
        state.status = status
        IndexRunner._write_state(db_path, state)
        storage = open_storage(db_path)
        try:
            storage.end_running_index_run(
                state.run_id,
                status,
                state.total_files,
                state.processed_files,
                state.failed_files,
                datetime.now(UTC).isoformat(),
            )
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def signal_stop(db_path: Path | None = None) -> None:
        """Ask the running background index to stop, without waiting for it to.

        Sets the same "stop" control the worker checks between files, then
        returns immediately - it does not wait or force-kill. The worker cleans
        up after itself (lock/control files, `index_runs`) once it actually
        exits on its own, whether that's right away (between files) or after
        finishing whatever file it's currently on (nothing left to check the
        signal at); either way nothing lingers, just not necessarily instantly.
        Use this when the caller shouldn't block on that - e.g. the desktop app
        closing. For an interactive "stop it now and tell me" (`vethuq index
        stop`), use `request_stop` instead.
        """
        db_path = db_path or default_db_path()
        if not IndexRunner.is_running(db_path)[0]:
            raise IndexRunnerError("No background index run is currently running.")
        IndexRunner._set_control(db_path, "stop")

    @staticmethod
    def request_stop(
        db_path: Path | None = None, *, timeout: float = _STOP_TIMEOUT_SECONDS
    ) -> None:
        """Stop the running background index and wait for confirmation.

        Signals the worker to finish the file it's currently on and exit rather
        than starting another one, then waits up to `timeout` seconds for it to
        do so before force-killing it - for an interactive caller (the CLI) that
        wants to know it actually stopped before returning. A caller that
        shouldn't block on that should use `signal_stop` instead.
        """
        db_path = db_path or default_db_path()
        running, pid = IndexRunner.is_running(db_path)
        if not running or pid is None:
            raise IndexRunnerError("No background index run is currently running.")

        IndexRunner._set_control(db_path, "stop")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and IndexRunner._is_pid_running(pid):
            time.sleep(0.25)
        force_killed = False
        if IndexRunner._is_pid_running(pid):
            IndexRunner._logger.warning(
                "Index worker pid=%d missed the stop timeout; force-killing it", pid
            )
            IndexRunner._force_kill(pid)
            force_killed = True

        state = IndexRunner.read_state(db_path, raw=True)
        if state is not None:
            IndexRunner._mark_run_ended(db_path, state, "stopped")
        IndexRunner._lock_path(db_path).unlink(missing_ok=True)
        IndexRunner._control_path(db_path).unlink(missing_ok=True)
        if force_killed:
            # A cooperative stop always finishes whichever file it's on before
            # exiting (nothing is left claimed) - only a force-kill can cut that
            # file off mid-processing, leaving its row claimed with no run left
            # to ever finish it.
            IndexRunner._reclaim_stuck_processing(db_path)

    @staticmethod
    def wait(
        pid: int,
        on_state: Callable[[IndexState], None] | None = None,
        *,
        poll_seconds: float = 1.0,
    ) -> IndexState | None:
        """Block until the run owned by `pid` reaches a terminal state, and return it.

        `on_state`, when given, is called with the run's state on every poll
        that finds it (including the final one) - for a caller that reports
        progress as it goes. If the process ends without ever reporting a state
        for `pid`, returns whatever state is on file instead (None, or an older
        run's) - a caller can tell by `state.pid != pid`.
        """
        while True:
            time.sleep(poll_seconds)
            state = IndexRunner.read_state()
            if state is not None and state.pid == pid:
                if on_state is not None:
                    on_state(state)
                if state.is_finished:
                    return state
                continue
            # No state yet for this pid - it may just be starting up (the worker
            # hasn't written its first state file yet), or it may genuinely be
            # gone (e.g. crashed before writing anything). Only stop waiting once
            # the process itself is confirmed no longer running.
            running, current_pid = IndexRunner.is_running()
            if not running or current_pid != pid:
                return IndexRunner.read_state()

    @staticmethod
    def request_pause(db_path: Path | None = None) -> None:
        db_path = db_path or default_db_path()
        running, _pid = IndexRunner.is_running(db_path)
        if not running:
            raise IndexRunnerError("No background index run is currently running.")
        IndexRunner._set_control(db_path, "pause")

    @staticmethod
    def request_resume(db_path: Path | None = None) -> None:
        db_path = db_path or default_db_path()
        running, _pid = IndexRunner.is_running(db_path)
        if not running:
            raise IndexRunnerError("No background index run is currently running.")
        IndexRunner._set_control(db_path, "run")

    @staticmethod
    def list_runs(storage: Storage, target: str | None = None, limit: int = 10) -> list[IndexRun]:
        """Return past index runs, most recent first, optionally filtered to one source.

        A run over "all sources" (`target` column IS NULL) covered every source,
        so it's included alongside runs targeted at just the given `target`.
        """
        rows = storage.list_index_runs(target, limit)
        return [IndexRun._from_row(row) for row in rows]

    @staticmethod
    def resolve_targets(storage: Storage, target: str | None) -> list[Source]:
        """Return the sources a run/status check against `target` would cover.

        `target=None` means every source eligible for indexing (not `removed`);
        a specific id/path resolves to just that one source. Shared with ETA
        estimation (`vethuq index status`), which needs the same source set to
        know which files are still pending.
        """
        if target is None:
            return [
                s for s in Sources.list_all(storage) if s.status in ("pending", "indexed", "error")
            ]
        return [Sources.get(storage, Sources.coerce(target))]

    @staticmethod
    def _run_worker(db_path: Path, target: str | None, *, restart: bool = False) -> None:
        # check_same_thread=False: `Quick.run_batch` below may hand this connection
        # to worker threads when `workers` > 1 - every use of it is already
        # serialized through `db_lock` there.
        storage = open_storage(db_path, check_same_thread=False)
        pid = os.getpid()
        started_at = datetime.now(UTC).isoformat()
        run_id: int | None = None
        stopped = False
        heartbeat: IndexRunner._Heartbeat | None = None
        mode = "restart" if restart else "run"
        try:
            sources = IndexRunner.resolve_targets(storage, target)
            total = sum(
                Pending.file_count(
                    storage, s, only_new_files=s.status != "pending", only_failed=restart
                )
                for s in sources
            )
            type_counts = Readers.new_file_type_counts()
            for source in sources:
                counts = Pending.file_type_counts(
                    storage, source, only_new_files=source.status != "pending", only_failed=restart
                )
                for file_type, count in counts.items():
                    type_counts[file_type] += count
            thread_workers_setting = IndexSettings.get_thread_workers(storage)
            workers = Scheduler.resolve_workers(storage, type_counts)

            run_id = storage.insert_index_run(target, mode, pid, total, workers, started_at)
            storage.commit()

            IndexRunner._logger.info(
                "Index run %d started: mode=%s target=%s files=%d workers=%d (thread_workers=%s)",
                run_id,
                mode,
                target or "all",
                total,
                workers,
                thread_workers_setting,
            )
            state = IndexState(
                run_id=run_id,
                pid=pid,
                target=target,
                mode=mode,
                status="running",
                total_files=total,
                processed_files=0,
                failed_files=0,
                thread_workers_setting=thread_workers_setting,
                workers=workers,
                current_files=[],
                started_at=started_at,
                updated_at=started_at,
                engine=OcrSettings.get_engine(storage),
            )
            IndexRunner._write_state(db_path, state)

            state_lock = threading.Lock()
            heartbeat = IndexRunner._Heartbeat(db_path, state, state_lock)
            heartbeat.start()

            def on_file_start(file_path: str) -> None:
                IndexRunner._logger.info("Processing %s", file_path)
                with state_lock:
                    state.phase = 1
                    state.current_files.append(file_path)
                    IndexRunner._write_state(db_path, state)

            def on_file_done(file_path: str, succeeded: bool | None) -> None:
                if succeeded is None:
                    IndexRunner._logger.info("Skipped %s (claimed by another run)", file_path)
                elif succeeded:
                    IndexRunner._logger.info("Indexed %s", file_path)
                else:
                    IndexRunner._logger.warning("Failed to index %s", file_path)
                with state_lock:
                    if file_path in state.current_files:
                        state.current_files.remove(file_path)
                    # None: another concurrently-running index run already
                    # claimed this file (see `Document.upsert`) - it doesn't
                    # count as processed/failed here, that run tracks it itself.
                    if succeeded is not None:
                        state.processed_files += 1
                        if not succeeded:
                            state.failed_files += 1
                    IndexRunner._write_state(db_path, state)

            def on_files_queued(count: int) -> None:
                # Files that turned up after the run started, e.g. added to a source.
                with state_lock:
                    state.total_files += count
                    IndexRunner._write_state(db_path, state)

            def on_unit_start(file_path: str, phase: int) -> None:
                with state_lock:
                    state.phase = phase
                    state.current_files.append(file_path)
                    IndexRunner._write_state(db_path, state)

            def on_unit_done(file_path: str) -> None:
                with state_lock:
                    if file_path in state.current_files:
                        state.current_files.remove(file_path)
                    state.deepened_pages += 1
                    IndexRunner._write_state(db_path, state)

            def on_workers_changed(new_workers: int) -> None:
                IndexRunner._logger.info("Active workers changed to %d", new_workers)
                with state_lock:
                    state.workers = new_workers
                    IndexRunner._write_state(db_path, state)

            def should_stop() -> bool:
                # Called from every active worker thread once `Quick.run_batch`
                # resolves to more than one worker - `state_lock` keeps their
                # writes to the shared state file from racing each other the
                # same way `on_file_start`/`on_file_done` already do.
                nonlocal stopped
                control = IndexRunner._read_control(db_path)
                while control == "pause":
                    with state_lock:
                        state.status = "paused"
                        IndexRunner._write_state(db_path, state)
                    time.sleep(IndexRunner._PAUSE_POLL_SECONDS)
                    control = IndexRunner._read_control(db_path)
                if control == "stop":
                    with state_lock:
                        stopped = True
                    return True
                with state_lock:
                    state.status = "running"
                return False

            Ocr.run_phased(
                storage,
                lambda: IndexRunner.resolve_targets(storage, target),
                only_failed=restart,
                workers=workers,
                on_file_start=on_file_start,
                on_file_done=on_file_done,
                on_workers_changed=on_workers_changed,
                should_stop=should_stop,
                on_files_queued=on_files_queued,
                on_unit_start=on_unit_start,
                on_unit_done=on_unit_done,
            )

            heartbeat.stop()
            final_status = "stopped" if stopped else "completed"
            IndexRunner._logger.info(
                "Index run %d %s: processed=%d failed=%d",
                run_id,
                final_status,
                state.processed_files,
                state.failed_files,
            )
            IndexRunner._mark_run_ended(db_path, state, final_status)
        except Exception:  # noqa: BLE001 - record the crash, then re-raise for the process exit code
            if heartbeat is not None:
                heartbeat.stop()
            IndexRunner._logger.exception("Index run crashed")
            if run_id is not None:
                storage.fail_index_run(run_id, datetime.now(UTC).isoformat())
            # Whatever file was in flight when this crashed is left claimed
            # ('processing') with nothing left to ever finish it - reset it so a
            # future run retries it instead of its claim blocking that forever.
            storage.fail_stuck_processing_document_index(
                IndexRunner._INTERRUPTED_MESSAGE, datetime.now(UTC).isoformat()
            )
            storage.commit()
            crashed_state = IndexRunner.read_state(db_path, raw=True)
            if crashed_state is not None:
                crashed_state.status = "failed"
                IndexRunner._write_state(db_path, crashed_state)
            raise
        finally:
            if heartbeat is not None:
                heartbeat.stop()
            IndexRunner._lock_path(db_path).unlink(missing_ok=True)
            IndexRunner._control_path(db_path).unlink(missing_ok=True)
            storage.close()

    @staticmethod
    def main() -> None:
        db_path = Path(sys.argv[1])
        target = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
        mode = sys.argv[3] if len(sys.argv) > 3 else "run"
        Logs.setup("index", db_path)
        IndexRunner._logger.info("Index worker pid=%d started", os.getpid())
        crash_trace = IndexRunner._enable_crash_trace(db_path)
        try:
            IndexRunner._run_worker(db_path, target, restart=mode == "restart")
        finally:
            IndexRunner._disable_crash_trace(db_path, crash_trace)
            IndexRunner._logger.info("Index worker pid=%d exiting", os.getpid())


if __name__ == "__main__":
    IndexRunner.main()
