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

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from vethuq_core.db import Db
from vethuq_core.db.queries import Index
from vethuq_core.ocr import Ocr, Pending, Readers, Scheduler
from vethuq_core.settings import IndexSettings, OcrSettings
from vethuq_core.source import Source, Sources


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

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> IndexRun:
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
    _LOG_FILENAME = "index_worker.log"
    _STOP_TIMEOUT_SECONDS = 5.0
    _PAUSE_POLL_SECONDS = 1.0
    # Bundled next to the desktop/CLI exes by the installer build. A frozen exe
    # can't be asked to run `-m vethuq_core.index.runner` (it would just start
    # the app again), so frozen builds spawn this dedicated worker exe instead.
    _WORKER_EXE_NAME = "vethuq-worker.exe"

    @staticmethod
    def _state_path(db_path: Path) -> Path:
        return db_path.parent / IndexRunner._STATE_FILENAME

    @staticmethod
    def _control_path(db_path: Path) -> Path:
        return db_path.parent / IndexRunner._CONTROL_FILENAME

    @staticmethod
    def _lock_path(db_path: Path) -> Path:
        return db_path.parent / IndexRunner._LOCK_FILENAME

    @staticmethod
    def log_path(db_path: Path | None = None) -> Path:
        """Path to the worker's log file, where a crash's traceback is written."""
        return (db_path or Db.default_db_path()).parent / IndexRunner._LOG_FILENAME

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
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
    def read_state(db_path: Path | None = None) -> IndexState | None:
        """Return the most recent run's live/last-known state, if one exists.

        The state file isn't durable history (that's `index_runs`) - it's just
        scratch progress for the current/last run - so a file left behind by an
        older version of this code, in a since-changed format, is treated the
        same as no state at all rather than raised as an error.
        """
        path = IndexRunner._state_path(db_path or Db.default_db_path())
        if not path.exists():
            return None
        try:
            return IndexState.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

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
        lock_path = IndexRunner._lock_path(db_path or Db.default_db_path())
        if not lock_path.exists():
            return False, None
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip())
        except ValueError:
            return False, None
        return IndexRunner._is_pid_running(pid), pid

    @staticmethod
    def _coerce_target(target: str) -> str | int:
        return int(target) if target.isdigit() else target

    @staticmethod
    def _worker_command(db_path: Path, target: str | None, restart: bool) -> list[str]:
        args = [str(db_path), target or "", "restart" if restart else "run"]
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name(IndexRunner._WORKER_EXE_NAME)
            if not worker.exists():
                raise IndexRunnerError(f"index worker not found at {worker}")
            return [str(worker), *args]
        return [sys.executable, "-m", "vethuq_core.index_runner", *args]

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
        db_path = db_path or Db.default_db_path()
        running, pid = IndexRunner.is_running(db_path)
        if running:
            raise AlreadyRunningError(f"An index run is already in progress (pid {pid}).")

        lock_path = IndexRunner._lock_path(db_path)
        if lock_path.exists():
            if not force:
                conn = Db.connect(db_path)
                try:
                    auto_clear = IndexSettings.get_stale_lock(conn) != "disable"
                finally:
                    conn.close()
                if not auto_clear:
                    raise StaleLockError(
                        "Found a lock left behind by a run that didn't exit cleanly. "
                        "Use --force to clear it and start a new run, or "
                        "`vethuq settings index stale-lock set enable` to clear it "
                        "automatically next time."
                    )
            lock_path.unlink(missing_ok=True)
            IndexRunner._reconcile_orphaned_run(db_path)

        conn = Db.connect(db_path)
        try:
            if target is not None:
                Sources.get(
                    conn, IndexRunner._coerce_target(target)
                )  # raises SourceNotFoundError if invalid
        finally:
            conn.close()

        IndexRunner._set_control(db_path, "run")

        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NO_WINDOW suppresses the console window a console-subsystem
            # child (python.exe) would otherwise pop up; CREATE_NEW_PROCESS_GROUP
            # keeps it from receiving Ctrl+C aimed at the parent's console.
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        # stderr goes to a log file (appended across runs) rather than DEVNULL -
        # if the worker crashes before it can record anything in index_runs or
        # the state file (e.g. an unexpected exception during startup), this is
        # the only place that failure is visible at all.
        with open(IndexRunner.log_path(db_path), "a", encoding="utf-8") as log_file:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
                IndexRunner._worker_command(db_path, target, restart),
                # Stops a onefile-frozen parent's bundle env from leaking into
                # the (also onefile) worker exe, which must unpack its own.
                env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                start_new_session=(sys.platform != "win32"),
                creationflags=creationflags,
            )
        IndexRunner._atomic_write(lock_path, str(process.pid))
        return process.pid

    @staticmethod
    def _reconcile_orphaned_run(db_path: Path) -> None:
        """Mark the bookkeeping left by a run that didn't exit cleanly as failed.

        Called right after clearing a stale lock, so `index status`/`index history`
        and the desktop app stop showing a run as still "running" once it's known
        the process behind it is gone.
        """
        state = IndexRunner.read_state(db_path)
        if state is not None and state.status == "running":
            IndexRunner._mark_run_ended(db_path, state, "failed")
            return
        conn = Db.connect(db_path)
        try:
            Index.fail_all_running(conn, datetime.now(UTC).isoformat())
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _mark_run_ended(db_path: Path, state: IndexState, status: str) -> None:
        state.status = status
        IndexRunner._write_state(db_path, state)
        conn = Db.connect(db_path)
        try:
            Index.end_running(
                conn,
                state.run_id,
                status,
                state.total_files,
                state.processed_files,
                state.failed_files,
                datetime.now(UTC).isoformat(),
            )
            conn.commit()
        finally:
            conn.close()

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
        db_path = db_path or Db.default_db_path()
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
        db_path = db_path or Db.default_db_path()
        running, pid = IndexRunner.is_running(db_path)
        if not running or pid is None:
            raise IndexRunnerError("No background index run is currently running.")

        IndexRunner._set_control(db_path, "stop")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and IndexRunner._is_pid_running(pid):
            time.sleep(0.25)
        if IndexRunner._is_pid_running(pid):
            IndexRunner._force_kill(pid)

        state = IndexRunner.read_state(db_path)
        if state is not None:
            IndexRunner._mark_run_ended(db_path, state, "stopped")
        IndexRunner._lock_path(db_path).unlink(missing_ok=True)
        IndexRunner._control_path(db_path).unlink(missing_ok=True)

    @staticmethod
    def request_pause(db_path: Path | None = None) -> None:
        db_path = db_path or Db.default_db_path()
        running, _pid = IndexRunner.is_running(db_path)
        if not running:
            raise IndexRunnerError("No background index run is currently running.")
        IndexRunner._set_control(db_path, "pause")

    @staticmethod
    def request_resume(db_path: Path | None = None) -> None:
        db_path = db_path or Db.default_db_path()
        running, _pid = IndexRunner.is_running(db_path)
        if not running:
            raise IndexRunnerError("No background index run is currently running.")
        IndexRunner._set_control(db_path, "run")

    @staticmethod
    def list_runs(
        conn: sqlite3.Connection, target: str | None = None, limit: int = 10
    ) -> list[IndexRun]:
        """Return past index runs, most recent first, optionally filtered to one source.

        A run over "all sources" (`target` column IS NULL) covered every source,
        so it's included alongside runs targeted at just the given `target`.
        """
        rows = Index.list_runs(conn, target, limit)
        return [IndexRun._from_row(row) for row in rows]

    @staticmethod
    def resolve_targets(conn: sqlite3.Connection, target: str | None) -> list[Source]:
        """Return the sources a run/status check against `target` would cover.

        `target=None` means every source eligible for indexing (not `removed`);
        a specific id/path resolves to just that one source. Shared with ETA
        estimation (`vethuq index status`), which needs the same source set to
        know which files are still pending.
        """
        if target is None:
            return [
                s for s in Sources.list_all(conn) if s.status in ("pending", "indexed", "error")
            ]
        return [Sources.get(conn, IndexRunner._coerce_target(target))]

    @staticmethod
    def _run_worker(db_path: Path, target: str | None, *, restart: bool = False) -> None:
        # check_same_thread=False: `Quick.run_batch` below may hand this connection
        # to worker threads when `workers` > 1 - every use of it is already
        # serialized through `db_lock` there.
        conn = Db.connect(db_path, check_same_thread=False)
        pid = os.getpid()
        started_at = datetime.now(UTC).isoformat()
        run_id: int | None = None
        stopped = False
        mode = "restart" if restart else "run"
        try:
            sources = IndexRunner.resolve_targets(conn, target)
            total = sum(
                Pending.file_count(
                    conn, s, only_new_files=s.status != "pending", only_failed=restart
                )
                for s in sources
            )
            type_counts = Readers.new_file_type_counts()
            for source in sources:
                counts = Pending.file_type_counts(
                    conn, source, only_new_files=source.status != "pending", only_failed=restart
                )
                for file_type, count in counts.items():
                    type_counts[file_type] += count
            thread_workers_setting = IndexSettings.get_thread_workers(conn)
            workers = Scheduler.resolve_workers(conn, type_counts)

            run_id = Index.insert_run(conn, target, mode, pid, total, workers, started_at)
            conn.commit()

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
                engine=OcrSettings.get_engine(conn),
            )
            IndexRunner._write_state(db_path, state)

            state_lock = threading.Lock()

            def on_file_start(file_path: str) -> None:
                with state_lock:
                    state.phase = 1
                    state.current_files.append(file_path)
                    IndexRunner._write_state(db_path, state)

            def on_file_done(file_path: str, succeeded: bool) -> None:
                with state_lock:
                    if file_path in state.current_files:
                        state.current_files.remove(file_path)
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
                conn,
                lambda: IndexRunner.resolve_targets(conn, target),
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

            final_status = "stopped" if stopped else "completed"
            IndexRunner._mark_run_ended(db_path, state, final_status)
        except Exception:  # noqa: BLE001 - record the crash, then re-raise for the process exit code
            if run_id is not None:
                Index.fail_run(conn, run_id, datetime.now(UTC).isoformat())
                conn.commit()
            crashed_state = IndexRunner.read_state(db_path)
            if crashed_state is not None:
                crashed_state.status = "failed"
                IndexRunner._write_state(db_path, crashed_state)
            raise
        finally:
            IndexRunner._lock_path(db_path).unlink(missing_ok=True)
            IndexRunner._control_path(db_path).unlink(missing_ok=True)
            conn.close()

    @staticmethod
    def main() -> None:
        db_path = Path(sys.argv[1])
        target = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
        mode = sys.argv[3] if len(sys.argv) > 3 else "run"
        IndexRunner._run_worker(db_path, target, restart=mode == "restart")


if __name__ == "__main__":
    IndexRunner.main()
