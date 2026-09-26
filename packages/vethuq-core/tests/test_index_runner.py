import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from vethuq_core import index_runner
from vethuq_core.db import connect
from vethuq_core.sources import SourceNotFoundError, add_source


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "vethuq.db"
    connect(path).close()
    return path


@pytest.fixture
def conn(db_path):
    connection = connect(db_path)
    yield connection
    connection.close()


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def test_read_state_ignores_old_incompatible_format(db_path):
    # Simulates a state file left behind by an older version of this code,
    # written before a field (e.g. "mode") existed.
    old_format = {
        "run_id": 1,
        "pid": 123,
        "target": None,
        "status": "completed",
        "total_files": 1,
        "processed_files": 1,
        "failed_files": 0,
        "current_file": None,
        "started_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    index_runner._atomic_write(index_runner._state_path(db_path), json.dumps(old_format))

    assert index_runner.read_state(db_path) is None


def _register_source(conn: sqlite3.Connection, tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    add_source(conn, folder)


def _fake_run_ocr(
    conn, source, *, only_new_files=False, only_failed=False, on_file_done=None, should_stop=None
):
    processed = []
    for file_path in ("a.pdf", "b.pdf", "c.pdf"):
        if should_stop is not None and should_stop():
            break
        processed.append(file_path)
        if on_file_done is not None:
            on_file_done(file_path)
    return processed


def test_run_worker_completes(db_path, conn, tmp_path):
    _register_source(conn, tmp_path)
    conn.close()

    with (
        patch.object(index_runner, "pending_file_count", return_value=3),
        patch.object(index_runner, "run_ocr", side_effect=_fake_run_ocr),
    ):
        index_runner._run_worker(db_path, None)

    state = index_runner.read_state(db_path)
    assert state is not None
    assert state.status == "completed"
    assert state.processed_files == 3
    assert not index_runner._lock_path(db_path).exists()

    result_conn = connect(db_path)
    row = result_conn.execute("SELECT * FROM index_runs").fetchone()
    result_conn.close()
    assert row["status"] == "completed"
    assert row["processed_files"] == 3


def test_run_worker_stops_when_requested(db_path, conn, tmp_path):
    _register_source(conn, tmp_path)
    conn.close()

    def fake_run_ocr(
        conn,
        source,
        *,
        only_new_files=False,
        only_failed=False,
        on_file_done=None,
        should_stop=None,
    ):
        processed = []
        for file_path in ("a.pdf", "b.pdf", "c.pdf"):
            if should_stop is not None and should_stop():
                break
            if file_path == "b.pdf":
                index_runner._set_control(db_path, "stop")
            processed.append(file_path)
            if on_file_done is not None:
                on_file_done(file_path)
        return processed

    with (
        patch.object(index_runner, "pending_file_count", return_value=3),
        patch.object(index_runner, "run_ocr", side_effect=fake_run_ocr),
    ):
        index_runner._run_worker(db_path, None)

    state = index_runner.read_state(db_path)
    assert state is not None
    assert state.status == "stopped"
    assert state.processed_files == 2


def test_run_worker_pauses_then_resumes(db_path, conn, tmp_path, monkeypatch):
    _register_source(conn, tmp_path)
    conn.close()

    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        index_runner._set_control(db_path, "run")

    monkeypatch.setattr(index_runner.time, "sleep", fake_sleep)

    def fake_run_ocr(
        conn,
        source,
        *,
        only_new_files=False,
        only_failed=False,
        on_file_done=None,
        should_stop=None,
    ):
        assert should_stop() is False
        index_runner._set_control(db_path, "pause")
        assert should_stop() is False
        return []

    with (
        patch.object(index_runner, "pending_file_count", return_value=0),
        patch.object(index_runner, "run_ocr", side_effect=fake_run_ocr),
    ):
        index_runner._run_worker(db_path, None)

    assert calls["n"] == 1
    state = index_runner.read_state(db_path)
    assert state is not None
    assert state.status == "completed"


def test_run_worker_restart_passes_only_failed(db_path, conn, tmp_path):
    _register_source(conn, tmp_path)
    conn.close()

    seen = {}

    def fake_run_ocr(
        conn,
        source,
        *,
        only_new_files=False,
        only_failed=False,
        on_file_done=None,
        should_stop=None,
    ):
        seen["only_failed"] = only_failed
        return []

    with (
        patch.object(index_runner, "pending_file_count", return_value=0) as fake_count,
        patch.object(index_runner, "run_ocr", side_effect=fake_run_ocr),
    ):
        index_runner._run_worker(db_path, None, restart=True)

    assert seen["only_failed"] is True
    assert fake_count.call_args.kwargs["only_failed"] is True

    result_conn = connect(db_path)
    row = result_conn.execute("SELECT mode FROM index_runs").fetchone()
    result_conn.close()
    assert row["mode"] == "restart"


def test_start_run_writes_lock_and_returns_pid(db_path, monkeypatch):
    monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(4321))

    pid = index_runner.start_run(None, db_path=db_path)

    assert pid == 4321
    assert index_runner._lock_path(db_path).read_text(encoding="utf-8").strip() == "4321"


def test_start_run_redirects_stderr_to_log_file(db_path, monkeypatch):
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["stderr"] = kwargs.get("stderr")
        return _FakeProcess(4321)

    monkeypatch.setattr(index_runner.subprocess, "Popen", fake_popen)

    index_runner.start_run(None, db_path=db_path)

    assert captured["stderr"] is not None
    assert captured["stderr"] != index_runner.subprocess.DEVNULL
    assert index_runner.log_path(db_path).exists()


def test_start_run_passes_restart_mode_to_worker_argv(db_path, monkeypatch):
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return _FakeProcess(4321)

    monkeypatch.setattr(index_runner.subprocess, "Popen", fake_popen)

    index_runner.start_run(None, restart=True, db_path=db_path)

    assert captured["argv"][-1] == "restart"


def test_start_run_raises_when_already_running(db_path, monkeypatch):
    monkeypatch.setattr(index_runner, "_is_pid_running", lambda pid: True)
    index_runner._atomic_write(index_runner._lock_path(db_path), "111")

    with pytest.raises(index_runner.AlreadyRunningError):
        index_runner.start_run(None, db_path=db_path)


def test_start_run_raises_on_stale_lock_without_force(db_path, monkeypatch):
    monkeypatch.setattr(index_runner, "_is_pid_running", lambda pid: False)
    index_runner._atomic_write(index_runner._lock_path(db_path), "999")

    with pytest.raises(index_runner.StaleLockError):
        index_runner.start_run(None, db_path=db_path)


def test_start_run_force_clears_stale_lock(db_path, monkeypatch):
    monkeypatch.setattr(index_runner, "_is_pid_running", lambda pid: False)
    index_runner._atomic_write(index_runner._lock_path(db_path), "999")
    monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(555))

    pid = index_runner.start_run(None, force=True, db_path=db_path)

    assert pid == 555


def test_start_run_raises_for_unknown_target(db_path):
    with pytest.raises(SourceNotFoundError):
        index_runner.start_run("does-not-exist", db_path=db_path)


def test_request_stop_raises_when_not_running(db_path):
    with pytest.raises(index_runner.IndexRunnerError):
        index_runner.request_stop(db_path=db_path)


def test_signal_stop_raises_when_not_running(db_path):
    with pytest.raises(index_runner.IndexRunnerError):
        index_runner.signal_stop(db_path=db_path)


def test_signal_stop_sets_control_without_waiting(db_path, monkeypatch):
    index_runner._atomic_write(index_runner._lock_path(db_path), "321")
    monkeypatch.setattr(index_runner, "_is_pid_running", lambda pid: True)
    sleep_calls = []
    monkeypatch.setattr(index_runner.time, "sleep", lambda s: sleep_calls.append(s))

    index_runner.signal_stop(db_path=db_path)

    assert index_runner._read_control(db_path) == "stop"
    assert sleep_calls == []
    # Unlike request_stop, signal_stop doesn't clean up the lock itself -
    # that's the worker's job once it actually exits.
    assert index_runner._lock_path(db_path).exists()


def test_request_stop_honors_custom_timeout(db_path, conn, tmp_path, monkeypatch):
    _register_source(conn, tmp_path)
    started_at = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO index_runs (target, status, pid, total_files, started_at) "
        "VALUES (NULL, 'running', 5150, 5, ?)",
        (started_at,),
    )
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()

    state = index_runner.IndexState(
        run_id=run_id,
        pid=5150,
        target=None,
        mode="run",
        status="running",
        total_files=5,
        processed_files=1,
        failed_files=0,
        current_file=None,
        started_at=started_at,
        updated_at=started_at,
    )
    index_runner._write_state(db_path, state)
    index_runner._atomic_write(index_runner._lock_path(db_path), "5150")

    monkeypatch.setattr(index_runner, "_is_pid_running", lambda pid: True)
    monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)
    force_kill_calls = []
    monkeypatch.setattr(index_runner, "_force_kill", force_kill_calls.append)

    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        clock["now"] += 1.0
        return clock["now"]

    monkeypatch.setattr(index_runner.time, "monotonic", fake_monotonic)

    index_runner.request_stop(db_path=db_path, timeout=3.0)

    assert force_kill_calls == [5150]
    # The deadline check runs once before the loop and once per iteration;
    # with a 1s-per-call fake clock and a 3s timeout, it should give up
    # (and force-kill) well before it would have for the ~5s default.
    assert clock["now"] < index_runner._STOP_TIMEOUT_SECONDS


def test_request_pause_raises_when_not_running(db_path):
    with pytest.raises(index_runner.IndexRunnerError):
        index_runner.request_pause(db_path=db_path)


def test_request_resume_raises_when_not_running(db_path):
    with pytest.raises(index_runner.IndexRunnerError):
        index_runner.request_resume(db_path=db_path)


def test_request_stop_marks_state_and_history(db_path, conn, tmp_path, monkeypatch):
    _register_source(conn, tmp_path)
    started_at = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO index_runs (target, status, pid, total_files, started_at) "
        "VALUES (NULL, 'running', 4242, 5, ?)",
        (started_at,),
    )
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()

    state = index_runner.IndexState(
        run_id=run_id,
        pid=4242,
        target=None,
        mode="run",
        status="running",
        total_files=5,
        processed_files=2,
        failed_files=0,
        current_file=None,
        started_at=started_at,
        updated_at=started_at,
    )
    index_runner._write_state(db_path, state)
    index_runner._atomic_write(index_runner._lock_path(db_path), "4242")

    calls = {"n": 0}

    def fake_alive(pid: int) -> bool:
        calls["n"] += 1
        return calls["n"] == 1

    monkeypatch.setattr(index_runner, "_is_pid_running", fake_alive)
    monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)

    index_runner.request_stop(db_path=db_path)

    assert not index_runner._lock_path(db_path).exists()
    final_state = index_runner.read_state(db_path)
    assert final_state is not None
    assert final_state.status == "stopped"

    result_conn = connect(db_path)
    row = result_conn.execute("SELECT status FROM index_runs WHERE id = ?", (run_id,)).fetchone()
    result_conn.close()
    assert row["status"] == "stopped"
