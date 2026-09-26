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
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from vethuq_core.db import connect, default_db_path
from vethuq_core.ocr import pending_file_count, run_ocr
from vethuq_core.sources import Source, get_source, list_sources

_STATE_FILENAME = "index_state.json"
_CONTROL_FILENAME = "index.control"
_LOCK_FILENAME = "index.lock"
_STOP_TIMEOUT_SECONDS = 5.0
_PAUSE_POLL_SECONDS = 1.0


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
    status: str  # "running" | "paused" | "completed" | "stopped" | "failed"
    total_files: int
    processed_files: int
    failed_files: int
    current_file: str | None
    started_at: str
    updated_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> IndexState:
        return cls(**json.loads(text))


def _state_path(db_path: Path) -> Path:
    return db_path.parent / _STATE_FILENAME


def _control_path(db_path: Path) -> Path:
    return db_path.parent / _CONTROL_FILENAME


def _lock_path(db_path: Path) -> Path:
    return db_path.parent / _LOCK_FILENAME


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _is_pid_running(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _force_kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def read_state(db_path: Path | None = None) -> IndexState | None:
    """Return the most recent run's live/last-known state, if one exists."""
    path = _state_path(db_path or default_db_path())
    if not path.exists():
        return None
    return IndexState.from_json(path.read_text(encoding="utf-8"))


def _write_state(db_path: Path, state: IndexState) -> None:
    state.updated_at = datetime.now(UTC).isoformat()
    _atomic_write(_state_path(db_path), state.to_json())


def _read_control(db_path: Path) -> str:
    path = _control_path(db_path)
    if not path.exists():
        return "run"
    return path.read_text(encoding="utf-8").strip() or "run"


def _set_control(db_path: Path, control: str) -> None:
    _atomic_write(_control_path(db_path), control)


def is_running(db_path: Path | None = None) -> tuple[bool, int | None]:
    """Return (running, pid). `running` is False if the lock is stale."""
    lock_path = _lock_path(db_path or default_db_path())
    if not lock_path.exists():
        return False, None
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False, None
    return _is_pid_running(pid), pid


def _coerce_target(target: str) -> str | int:
    return int(target) if target.isdigit() else target


def start_run(
    target: str | None = None, *, force: bool = False, db_path: Path | None = None
) -> int:
    """Launch OCR indexing as a detached background process. Returns its pid."""
    db_path = db_path or default_db_path()
    running, pid = is_running(db_path)
    if running:
        raise AlreadyRunningError(f"An index run is already in progress (pid {pid}).")

    lock_path = _lock_path(db_path)
    if lock_path.exists() and not force:
        raise StaleLockError(
            "Found a lock left behind by a run that didn't exit cleanly. "
            "Use --force to clear it and start a new run."
        )
    lock_path.unlink(missing_ok=True)

    conn = connect(db_path)
    try:
        if target is not None:
            get_source(conn, _coerce_target(target))  # raises SourceNotFoundError if invalid
    finally:
        conn.close()

    _set_control(db_path, "run")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user-controlled binary
        [sys.executable, "-m", "vethuq_core.index_runner", str(db_path), target or ""],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(sys.platform != "win32"),
        creationflags=creationflags,
    )
    _atomic_write(lock_path, str(process.pid))
    return process.pid


def _mark_run_ended(db_path: Path, state: IndexState, status: str) -> None:
    state.status = status
    _write_state(db_path, state)
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE index_runs SET status = ?, processed_files = ?, failed_files = ?, "
            "completed_at = ? WHERE id = ? AND status = 'running'",
            (
                status,
                state.processed_files,
                state.failed_files,
                datetime.now(UTC).isoformat(),
                state.run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def request_stop(db_path: Path | None = None) -> None:
    db_path = db_path or default_db_path()
    running, pid = is_running(db_path)
    if not running or pid is None:
        raise IndexRunnerError("No background index run is currently running.")

    _set_control(db_path, "stop")
    deadline = time.monotonic() + _STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline and _is_pid_running(pid):
        time.sleep(0.25)
    if _is_pid_running(pid):
        _force_kill(pid)

    state = read_state(db_path)
    if state is not None:
        _mark_run_ended(db_path, state, "stopped")
    _lock_path(db_path).unlink(missing_ok=True)
    _control_path(db_path).unlink(missing_ok=True)


def request_pause(db_path: Path | None = None) -> None:
    db_path = db_path or default_db_path()
    running, _pid = is_running(db_path)
    if not running:
        raise IndexRunnerError("No background index run is currently running.")
    _set_control(db_path, "pause")


def request_resume(db_path: Path | None = None) -> None:
    db_path = db_path or default_db_path()
    running, _pid = is_running(db_path)
    if not running:
        raise IndexRunnerError("No background index run is currently running.")
    _set_control(db_path, "run")


def _resolve_targets(conn: sqlite3.Connection, target: str | None) -> list[Source]:
    if target is None:
        return [s for s in list_sources(conn) if s.status in ("pending", "indexed", "error")]
    return [get_source(conn, _coerce_target(target))]


def _run_worker(db_path: Path, target: str | None) -> None:
    conn = connect(db_path)
    pid = os.getpid()
    started_at = datetime.now(UTC).isoformat()
    run_id: int | None = None
    stopped = False
    try:
        sources = _resolve_targets(conn, target)
        total = sum(
            pending_file_count(conn, s, only_new_files=s.status != "pending") for s in sources
        )

        cursor = conn.execute(
            "INSERT INTO index_runs (target, status, pid, total_files, started_at) "
            "VALUES (?, 'running', ?, ?, ?)",
            (target, pid, total, started_at),
        )
        conn.commit()
        run_id = cursor.lastrowid
        assert run_id is not None

        state = IndexState(
            run_id=run_id,
            pid=pid,
            target=target,
            status="running",
            total_files=total,
            processed_files=0,
            failed_files=0,
            current_file=None,
            started_at=started_at,
            updated_at=started_at,
        )
        _write_state(db_path, state)

        def on_file_done(file_path: str) -> None:
            state.processed_files += 1
            state.current_file = file_path
            doc = conn.execute(
                "SELECT status FROM document_index WHERE file_path = ?", (file_path,)
            ).fetchone()
            if doc is not None and doc["status"] == "error":
                state.failed_files += 1
            _write_state(db_path, state)

        def should_stop() -> bool:
            nonlocal stopped
            control = _read_control(db_path)
            while control == "pause":
                state.status = "paused"
                _write_state(db_path, state)
                time.sleep(_PAUSE_POLL_SECONDS)
                control = _read_control(db_path)
            if control == "stop":
                stopped = True
                return True
            state.status = "running"
            return False

        for source in sources:
            run_ocr(
                conn,
                source,
                only_new_files=source.status != "pending",
                on_file_done=on_file_done,
                should_stop=should_stop,
            )
            if stopped:
                break

        final_status = "stopped" if stopped else "completed"
        _mark_run_ended(db_path, state, final_status)
    except Exception:  # noqa: BLE001 - record the crash, then re-raise for the process exit code
        if run_id is not None:
            conn.execute(
                "UPDATE index_runs SET status = 'failed', completed_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), run_id),
            )
            conn.commit()
        crashed_state = read_state(db_path)
        if crashed_state is not None:
            crashed_state.status = "failed"
            _write_state(db_path, crashed_state)
        raise
    finally:
        _lock_path(db_path).unlink(missing_ok=True)
        _control_path(db_path).unlink(missing_ok=True)
        conn.close()


def main() -> None:
    db_path = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    _run_worker(db_path, target)


if __name__ == "__main__":
    main()
