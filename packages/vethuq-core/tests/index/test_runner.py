import faulthandler
import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from vethuq_core.db import Db
from vethuq_core.index import IndexRunner
from vethuq_core.index import runner as index_runner
from vethuq_core.logs import Logs
from vethuq_core.ocr import Ocr, Pending
from vethuq_core.paths import Paths
from vethuq_core.sources import SourceNotFoundError, Sources
from vethuq_core.storage import Storage


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "vethuq.db"
    Db.connect(path).close()
    return path


@pytest.fixture
def conn(db_path):
    connection = Db.connect(db_path)
    yield connection
    connection.close()


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _register_source(storage: Storage, tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    Sources.add(storage, folder)


def _fake_run_ocr_phased(
    storage,
    resolve_sources,
    *,
    only_failed=False,
    workers=1,
    on_file_start=None,
    on_file_done=None,
    on_workers_changed=None,
    should_stop=None,
    **_phase_callbacks,
):
    processed = []
    for file_path in ("a.pdf", "b.pdf", "c.pdf"):
        if should_stop is not None and should_stop():
            break
        if on_file_start is not None:
            on_file_start(file_path)
        processed.append(file_path)
        if on_file_done is not None:
            on_file_done(file_path, True)
    return processed


def _insert_processing_row(conn: sqlite3.Connection, file_path: str) -> None:
    """Insert a `document_index` row left claimed ('processing') under the registered source."""
    now = datetime.now(UTC).isoformat()
    document_id = conn.execute("INSERT INTO documents (created_at) VALUES (?)", (now,)).lastrowid
    source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO document_index "
        "(source_id, document_id, file_path, file_type, status, started_at) "
        "VALUES (?, ?, ?, 'pdf', 'processing', ?)",
        (source_id, document_id, file_path, now),
    )
    conn.commit()


def _write_running_state(db_path: Path, conn: sqlite3.Connection, pid: int) -> None:
    """Record a run as running (in `index_runs`, the state file and the lock) for `pid`."""
    started_at = datetime.now(UTC).isoformat()
    run_id = conn.execute(
        "INSERT INTO index_runs (target, status, pid, total_files, started_at) "
        "VALUES (NULL, 'running', ?, 1, ?)",
        (pid, started_at),
    ).lastrowid
    assert run_id is not None
    conn.commit()
    state = index_runner.IndexState(
        run_id=run_id,
        pid=pid,
        target=None,
        mode="run",
        status="running",
        total_files=1,
        processed_files=0,
        failed_files=0,
        thread_workers_setting="1",
        workers=1,
        current_files=[],
        started_at=started_at,
        updated_at=started_at,
    )
    IndexRunner._write_state(db_path, state)
    IndexRunner._atomic_write(IndexRunner._lock_path(db_path), str(pid))


def _document_index_row(db_path: Path, file_path: str) -> sqlite3.Row:
    result_conn = Db.connect(db_path)
    try:
        return result_conn.execute(
            "SELECT status, error_message FROM document_index WHERE file_path = ?", (file_path,)
        ).fetchone()
    finally:
        result_conn.close()


class TestReadState:
    def test_read_state_ignores_old_incompatible_format(self, db_path):
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
        IndexRunner._atomic_write(IndexRunner._state_path(db_path), json.dumps(old_format))

        assert IndexRunner.read_state(db_path) is None


class TestRunWorker:
    def test_run_worker_completes(self, db_path, conn, storage: Storage, tmp_path):
        _register_source(storage, tmp_path)
        conn.close()

        with (
            patch.object(Pending, "file_count", return_value=3),
            patch.object(Ocr, "run_phased", side_effect=_fake_run_ocr_phased),
        ):
            IndexRunner._run_worker(db_path, None)

        state = IndexRunner.read_state(db_path)
        assert state is not None
        assert state.status == "completed"
        assert state.processed_files == 3
        assert state.current_files == []
        assert not IndexRunner._lock_path(db_path).exists()

        result_conn = Db.connect(db_path)
        row = result_conn.execute("SELECT * FROM index_runs").fetchone()
        result_conn.close()
        assert row["status"] == "completed"
        assert row["processed_files"] == 3

    def test_run_worker_crash_resets_stuck_processing_document_index_row(
        self, db_path, conn, storage: Storage, tmp_path
    ):
        _register_source(storage, tmp_path)
        _insert_processing_row(conn, "/docs/stuck.pdf")
        conn.close()

        with (
            patch.object(Pending, "file_count", return_value=1),
            patch.object(Ocr, "run_phased", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            IndexRunner._run_worker(db_path, None)

        row = _document_index_row(db_path, "/docs/stuck.pdf")
        # The file this crashed run had claimed is left retryable rather than
        # permanently stuck - nothing will ever finish processing it otherwise.
        assert row["status"] == "error"
        assert row["error_message"] is not None

    def test_run_worker_stops_when_requested(self, db_path, conn, storage: Storage, tmp_path):
        _register_source(storage, tmp_path)
        conn.close()

        def fake_run_ocr_phased(
            storage,
            resolve_sources,
            *,
            only_failed=False,
            workers=1,
            on_file_start=None,
            on_file_done=None,
            on_workers_changed=None,
            should_stop=None,
            **_phase_callbacks,
        ):
            processed = []
            for file_path in ("a.pdf", "b.pdf", "c.pdf"):
                if should_stop is not None and should_stop():
                    break
                if file_path == "b.pdf":
                    IndexRunner._set_control(db_path, "stop")
                if on_file_start is not None:
                    on_file_start(file_path)
                processed.append(file_path)
                if on_file_done is not None:
                    on_file_done(file_path, True)
            return processed

        with (
            patch.object(Pending, "file_count", return_value=3),
            patch.object(Ocr, "run_phased", side_effect=fake_run_ocr_phased),
        ):
            IndexRunner._run_worker(db_path, None)

        state = IndexRunner.read_state(db_path)
        assert state is not None
        assert state.status == "stopped"
        assert state.processed_files == 2

    def test_run_worker_pauses_then_resumes(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        _register_source(storage, tmp_path)
        conn.close()

        calls = {"n": 0}

        def fake_sleep(_seconds: float) -> None:
            calls["n"] += 1
            IndexRunner._set_control(db_path, "run")

        monkeypatch.setattr(index_runner.time, "sleep", fake_sleep)

        def fake_run_ocr_phased(
            storage,
            resolve_sources,
            *,
            only_failed=False,
            workers=1,
            on_file_start=None,
            on_file_done=None,
            on_workers_changed=None,
            should_stop=None,
            **_phase_callbacks,
        ):
            assert should_stop() is False
            IndexRunner._set_control(db_path, "pause")
            assert should_stop() is False
            return []

        with (
            patch.object(Pending, "file_count", return_value=0),
            patch.object(Ocr, "run_phased", side_effect=fake_run_ocr_phased),
        ):
            IndexRunner._run_worker(db_path, None)

        assert calls["n"] == 1
        state = IndexRunner.read_state(db_path)
        assert state is not None
        assert state.status == "completed"

    def test_run_worker_restart_passes_only_failed(self, db_path, conn, storage: Storage, tmp_path):
        _register_source(storage, tmp_path)
        conn.close()

        seen = {}

        def fake_run_ocr_phased(
            storage,
            resolve_sources,
            *,
            only_failed=False,
            workers=1,
            on_file_start=None,
            on_file_done=None,
            on_workers_changed=None,
            should_stop=None,
            **_phase_callbacks,
        ):
            seen["only_failed"] = only_failed
            return []

        with (
            patch.object(Pending, "file_count", return_value=0) as fake_count,
            patch.object(Ocr, "run_phased", side_effect=fake_run_ocr_phased),
        ):
            IndexRunner._run_worker(db_path, None, restart=True)

        assert seen["only_failed"] is True
        assert fake_count.call_args.kwargs["only_failed"] is True

        result_conn = Db.connect(db_path)
        row = result_conn.execute("SELECT mode FROM index_runs").fetchone()
        result_conn.close()
        assert row["mode"] == "restart"


class TestStartRun:
    def test_start_run_writes_lock_and_returns_pid(self, db_path, monkeypatch):
        monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(4321))

        pid = IndexRunner.start_run(None, db_path=db_path)

        assert pid == 4321
        assert IndexRunner._lock_path(db_path).read_text(encoding="utf-8").strip() == "4321"

    def test_start_run_logs_worker_start_to_index_log(self, db_path, monkeypatch):
        monkeypatch.setattr(
            index_runner.subprocess, "Popen", lambda argv, **kwargs: _FakeProcess(4321)
        )

        IndexRunner.start_run(None, db_path=db_path)
        for handler in IndexRunner._logger.handlers:
            handler.flush()

        assert "Started index worker pid=4321" in IndexRunner.log_path(db_path).read_text(
            encoding="utf-8"
        )

    def test_start_run_passes_restart_mode_to_worker_argv(self, db_path, monkeypatch):
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = argv
            return _FakeProcess(4321)

        monkeypatch.setattr(index_runner.subprocess, "Popen", fake_popen)

        IndexRunner.start_run(None, restart=True, db_path=db_path)

        assert captured["argv"][-1] == "restart"

    def test_start_run_raises_when_already_running(self, db_path, monkeypatch):
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "111")

        with pytest.raises(index_runner.AlreadyRunningError):
            IndexRunner.start_run(None, db_path=db_path)

    def test_start_run_raises_on_stale_lock_when_disabled(
        self, db_path, storage: Storage, monkeypatch
    ):
        from vethuq_core.settings import IndexSettings

        IndexSettings.set_stale_lock(storage, "disable")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")

        with pytest.raises(index_runner.StaleLockError):
            IndexRunner.start_run(None, db_path=db_path)

    def test_start_run_force_clears_stale_lock(self, db_path, storage: Storage, monkeypatch):
        from vethuq_core.settings import IndexSettings

        IndexSettings.set_stale_lock(storage, "disable")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(555))

        pid = IndexRunner.start_run(None, force=True, db_path=db_path)

        assert pid == 555

    def test_start_run_auto_clears_stale_lock_by_default(self, db_path, monkeypatch):
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(555))

        pid = IndexRunner.start_run(None, db_path=db_path)

        assert pid == 555

    def test_start_run_reconciles_orphaned_run_as_failed(self, db_path, conn, monkeypatch):
        started_at = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO index_runs (id, mode, status, pid, started_at) "
            "VALUES (1, 'run', 'running', 999, ?)",
            (started_at,),
        )
        conn.commit()
        state = index_runner.IndexState(
            run_id=1,
            pid=999,
            target=None,
            mode="run",
            status="running",
            total_files=3,
            processed_files=1,
            failed_files=0,
            thread_workers_setting="0",
            workers=1,
            current_files=[],
            started_at=started_at,
            updated_at=started_at,
        )
        IndexRunner._write_state(db_path, state)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(555))

        IndexRunner.start_run(None, db_path=db_path)

        row = conn.execute("SELECT status FROM index_runs WHERE id = 1").fetchone()
        assert row["status"] == "failed"
        assert IndexRunner.read_state(db_path).status == "failed"

    def test_start_run_reconciles_stuck_processing_document_index_row(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        _register_source(storage, tmp_path)
        _insert_processing_row(conn, "/docs/stuck.pdf")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        monkeypatch.setattr(index_runner.subprocess, "Popen", lambda *a, **k: _FakeProcess(555))

        IndexRunner.start_run(None, db_path=db_path)

        row = _document_index_row(db_path, "/docs/stuck.pdf")
        # Nothing was still working on this row once its run's lock was found
        # stale - its claim ('processing') would otherwise block it from ever
        # being reclaimed, so it's reset to a retryable state instead.
        assert row["status"] == "error"
        assert row["error_message"] is not None

    def test_start_run_raises_for_unknown_target(self, db_path):
        with pytest.raises(SourceNotFoundError):
            IndexRunner.start_run("does-not-exist", db_path=db_path)


class TestControl:
    def test_request_stop_raises_when_not_running(self, db_path):
        with pytest.raises(index_runner.IndexRunnerError):
            IndexRunner.request_stop(db_path=db_path)

    def test_signal_stop_raises_when_not_running(self, db_path):
        with pytest.raises(index_runner.IndexRunnerError):
            IndexRunner.signal_stop(db_path=db_path)

    def test_signal_stop_sets_control_without_waiting(self, db_path, monkeypatch):
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "321")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        sleep_calls = []
        monkeypatch.setattr(index_runner.time, "sleep", lambda s: sleep_calls.append(s))

        IndexRunner.signal_stop(db_path=db_path)

        assert IndexRunner._read_control(db_path) == "stop"
        assert sleep_calls == []
        # Unlike request_stop, signal_stop doesn't clean up the lock itself -
        # that's the worker's job once it actually exits.
        assert IndexRunner._lock_path(db_path).exists()

    def test_request_stop_honors_custom_timeout(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        _register_source(storage, tmp_path)
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
            thread_workers_setting="1",
            workers=1,
            current_files=[],
            started_at=started_at,
            updated_at=started_at,
        )
        IndexRunner._write_state(db_path, state)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "5150")

        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)
        force_kill_calls: list[int] = []
        monkeypatch.setattr(IndexRunner, "_force_kill", force_kill_calls.append)

        clock = {"now": 0.0}

        def fake_monotonic() -> float:
            clock["now"] += 1.0
            return clock["now"]

        monkeypatch.setattr(index_runner.time, "monotonic", fake_monotonic)

        IndexRunner.request_stop(db_path=db_path, timeout=3.0)

        assert force_kill_calls == [5150]
        # The deadline check runs once before the loop and once per iteration;
        # with a 1s-per-call fake clock and a 3s timeout, it should give up
        # (and force-kill) well before it would have for the ~5s default.
        assert clock["now"] < IndexRunner._STOP_TIMEOUT_SECONDS

    def test_request_stop_force_kill_resets_stuck_processing_document_index_row(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        _register_source(storage, tmp_path)
        _insert_processing_row(conn, "/docs/stuck.pdf")
        _write_running_state(db_path, conn, 7777)
        conn.close()

        # Never reports as stopped on its own - forces the force-kill branch.
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)
        force_kill_calls: list[int] = []
        monkeypatch.setattr(IndexRunner, "_force_kill", force_kill_calls.append)

        clock = {"now": 0.0}

        def fake_monotonic() -> float:
            clock["now"] += 1.0
            return clock["now"]

        monkeypatch.setattr(index_runner.time, "monotonic", fake_monotonic)

        IndexRunner.request_stop(db_path=db_path, timeout=3.0)

        assert force_kill_calls == [7777]
        row = _document_index_row(db_path, "/docs/stuck.pdf")
        # A cooperative stop always finishes its current file first; only a
        # force-kill can cut it off mid-processing with its claim never released.
        assert row["status"] == "error"
        assert row["error_message"] is not None

    def test_request_stop_graceful_leaves_processing_rows_untouched(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        _register_source(storage, tmp_path)
        _insert_processing_row(conn, "/docs/still-processing.pdf")
        _write_running_state(db_path, conn, 8888)
        conn.close()

        calls = {"n": 0}

        def fake_alive(pid: int) -> bool:
            calls["n"] += 1
            return calls["n"] == 1  # alive on the first check, exited by the next

        monkeypatch.setattr(IndexRunner, "_is_pid_running", fake_alive)
        monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)
        force_kill_calls: list[int] = []
        monkeypatch.setattr(IndexRunner, "_force_kill", force_kill_calls.append)

        IndexRunner.request_stop(db_path=db_path)

        assert force_kill_calls == []
        # This row isn't necessarily stuck - a worker that stopped on its own can
        # still be mid-write on its last file, so a graceful stop must not touch
        # 'processing' rows the way a force-kill's reclaim does.
        assert _document_index_row(db_path, "/docs/still-processing.pdf")["status"] == "processing"

    def test_request_pause_raises_when_not_running(self, db_path):
        with pytest.raises(index_runner.IndexRunnerError):
            IndexRunner.request_pause(db_path=db_path)

    def test_request_resume_raises_when_not_running(self, db_path):
        with pytest.raises(index_runner.IndexRunnerError):
            IndexRunner.request_resume(db_path=db_path)

    def test_request_stop_marks_state_and_history(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        _register_source(storage, tmp_path)
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
            thread_workers_setting="1",
            workers=1,
            current_files=[],
            started_at=started_at,
            updated_at=started_at,
        )
        IndexRunner._write_state(db_path, state)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "4242")

        calls = {"n": 0}

        def fake_alive(pid: int) -> bool:
            calls["n"] += 1
            return calls["n"] == 1

        monkeypatch.setattr(IndexRunner, "_is_pid_running", fake_alive)
        monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)

        IndexRunner.request_stop(db_path=db_path)

        assert not IndexRunner._lock_path(db_path).exists()
        final_state = IndexRunner.read_state(db_path)
        assert final_state is not None
        assert final_state.status == "stopped"

        result_conn = Db.connect(db_path)
        row = result_conn.execute(
            "SELECT status FROM index_runs WHERE id = ?", (run_id,)
        ).fetchone()
        result_conn.close()
        assert row["status"] == "stopped"


def _state(pid: int, status: str) -> index_runner.IndexState:
    now = datetime.now(UTC).isoformat()
    return index_runner.IndexState(
        run_id=1,
        pid=pid,
        target=None,
        mode="run",
        status=status,
        total_files=1,
        processed_files=0,
        failed_files=0,
        thread_workers_setting="0",
        workers=1,
        current_files=[],
        started_at=now,
        updated_at=now,
    )


class TestWait:
    def test_returns_the_final_state_and_reports_every_state_seen(self, db_path, monkeypatch):
        monkeypatch.setattr(Db, "default_db_path", staticmethod(lambda: db_path))
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        IndexRunner._write_state(db_path, _state(77, "running"))
        seen: list[str] = []

        def fake_sleep(_seconds: float) -> None:
            if len(seen) == 1:  # the next poll finds the run finished
                IndexRunner._write_state(db_path, _state(77, "completed"))

        monkeypatch.setattr(index_runner.time, "sleep", fake_sleep)

        final = IndexRunner.wait(77, lambda state: seen.append(state.status))

        assert final is not None and final.status == "completed"
        assert seen == ["running", "completed"]

    def test_returns_without_a_state_when_the_process_is_gone(self, db_path, monkeypatch):
        monkeypatch.setattr(Db, "default_db_path", staticmethod(lambda: db_path))
        monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)

        assert IndexRunner.wait(77) is None


class TestDeadWorker:
    def test_dead_worker_reads_as_failed_and_is_recorded(self, db_path, conn, monkeypatch):
        _write_running_state(db_path, conn, pid=999)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)

        state = IndexRunner.read_state(db_path)

        assert state is not None
        assert (state.status, state.error) == ("failed", IndexRunner._DIED_MESSAGE)
        assert IndexRunner.read_state(db_path, raw=True).status == "failed"
        assert conn.execute("SELECT status FROM index_runs").fetchone()["status"] == "failed"

    def test_live_worker_stays_running(self, db_path, conn, monkeypatch):
        _write_running_state(db_path, conn, pid=999)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)

        state = IndexRunner.read_state(db_path)

        assert state is not None
        assert (state.status, state.error) == ("running", None)

    def test_a_live_launcher_counts_even_when_the_worker_pid_differs(
        self, db_path, conn, monkeypatch
    ):
        _write_running_state(db_path, conn, pid=999)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "555")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: pid == 555)

        assert IndexRunner.read_state(db_path).status == "running"

    def test_raw_read_leaves_a_dead_state_untouched(self, db_path, conn, monkeypatch):
        _write_running_state(db_path, conn, pid=999)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)

        assert IndexRunner.read_state(db_path, raw=True).status == "running"
        assert conn.execute("SELECT status FROM index_runs").fetchone()["status"] == "running"

    def test_a_finished_state_is_never_second_guessed(self, db_path, monkeypatch):
        IndexRunner._write_state(db_path, _state(999, "completed"))
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)

        state = IndexRunner.read_state(db_path)

        assert (state.status, state.error) == ("completed", None)

    def test_wait_ends_with_the_failed_state_when_the_worker_dies(self, db_path, monkeypatch):
        monkeypatch.setattr(Db, "default_db_path", staticmethod(lambda: db_path))
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        monkeypatch.setattr(index_runner.time, "sleep", lambda _seconds: None)
        IndexRunner._write_state(db_path, _state(77, "running"))

        final = IndexRunner.wait(77)

        assert final is not None and final.status == "failed"

    def test_is_stalled_only_for_an_active_run_gone_quiet(self):
        quiet = _state(1, "running")
        quiet.updated_at = "2000-01-01T00:00:00+00:00"
        finished = _state(1, "completed")
        finished.updated_at = "2000-01-01T00:00:00+00:00"

        assert IndexRunner.is_stalled(quiet) is True
        assert IndexRunner.is_stalled(_state(1, "running")) is False
        assert IndexRunner.is_stalled(finished) is False


class TestCrashTrace:
    TRACE = (
        "Windows fatal exception: access violation\n\n"
        "Current thread 0x00005664 (most recent call first):\n"
        '  File "static_infer.py", line 261 in __call__\n'
    )

    @staticmethod
    def _index_log(db_path) -> str:
        Logs.setup("index", db_path)
        path = IndexRunner.log_path(db_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_a_trace_is_moved_into_the_index_log_and_removed(self, db_path):
        Logs.setup("index", db_path)
        IndexRunner.crash_log_path(db_path).write_text(self.TRACE, encoding="utf-8")

        first_line = IndexRunner._collect_crash_trace(db_path)

        assert first_line == "Windows fatal exception: access violation"
        assert not IndexRunner.crash_log_path(db_path).exists()
        log = self._index_log(db_path)
        assert "static_infer.py" in log and "access violation" in log

    def test_no_trace_means_nothing_to_collect(self, db_path):
        assert IndexRunner._collect_crash_trace(db_path) is None
        IndexRunner.crash_log_path(db_path).write_text("  \n", encoding="utf-8")
        assert IndexRunner._collect_crash_trace(db_path) is None
        assert not IndexRunner.crash_log_path(db_path).exists()

    def test_a_dead_worker_with_a_trace_reports_the_crash(self, db_path, conn, monkeypatch):
        _write_running_state(db_path, conn, pid=999)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner.crash_log_path(db_path).write_text(self.TRACE, encoding="utf-8")

        state = IndexRunner.read_state(db_path)

        assert state is not None and state.status == "failed"
        assert "access violation" in (state.error or "")
        assert "index log" in (state.error or "")
        assert "static_infer.py" in self._index_log(db_path)

    def test_a_dead_worker_is_recorded_in_the_index_log(self, db_path, conn, monkeypatch):
        _write_running_state(db_path, conn, pid=999)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)

        state = IndexRunner.read_state(db_path)

        assert state is not None and state.error == IndexRunner._DIED_MESSAGE
        assert "marking it failed" in self._index_log(db_path)

    def test_the_worker_traces_to_the_crash_file_and_cleans_up_on_a_clean_exit(self, db_path):
        was_enabled = faulthandler.is_enabled()
        try:
            handle = IndexRunner._enable_crash_trace(db_path)

            assert handle is not None
            assert faulthandler.is_enabled()
            assert IndexRunner.crash_log_path(db_path).exists()

            IndexRunner._disable_crash_trace(db_path, handle)

            assert not faulthandler.is_enabled()
            assert not IndexRunner.crash_log_path(db_path).exists()
        finally:
            if was_enabled:
                faulthandler.enable()

    def test_starting_a_worker_reports_a_trace_the_last_one_left(self, db_path):
        was_enabled = faulthandler.is_enabled()
        Logs.setup("index", db_path)
        IndexRunner.crash_log_path(db_path).write_text(self.TRACE, encoding="utf-8")
        try:
            handle = IndexRunner._enable_crash_trace(db_path)
            IndexRunner._disable_crash_trace(db_path, handle)
        finally:
            if was_enabled:
                faulthandler.enable()

        assert "static_infer.py" in self._index_log(db_path)


class TestHeartbeat:
    def test_refreshes_the_state_until_stopped(self, db_path, monkeypatch):
        monkeypatch.setattr(IndexRunner, "HEARTBEAT_SECONDS", 0.01)
        state = _state(1, "running")
        state.updated_at = "2000-01-01T00:00:00+00:00"
        IndexRunner._write_state(db_path, state)
        stale_at = IndexRunner.read_state(db_path, raw=True).updated_at
        heartbeat = IndexRunner._Heartbeat(db_path, state, threading.Lock())

        heartbeat.start()
        deadline = time.monotonic() + 5
        while (
            IndexRunner.read_state(db_path, raw=True).updated_at == stale_at
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        heartbeat.stop()

        refreshed = IndexRunner.read_state(db_path, raw=True).updated_at
        assert refreshed != stale_at
        time.sleep(0.05)
        assert IndexRunner.read_state(db_path, raw=True).updated_at == refreshed

    def test_stop_is_safe_to_repeat(self, db_path):
        heartbeat = IndexRunner._Heartbeat(db_path, _state(1, "running"), threading.Lock())
        heartbeat.start()

        heartbeat.stop()
        heartbeat.stop()

    def test_worker_keeps_beating_through_one_long_step(
        self, db_path, conn, storage: Storage, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(IndexRunner, "HEARTBEAT_SECONDS", 0.01)
        _register_source(storage, tmp_path)
        conn.close()
        writes: list[str] = []
        real_write = IndexRunner._write_state

        def counting_write(path, state):
            writes.append(state.status)
            real_write(path, state)

        monkeypatch.setattr(IndexRunner, "_write_state", staticmethod(counting_write))

        def one_long_step(storage, resolve_sources, **_kwargs):
            before = len(writes)
            time.sleep(0.3)
            assert len(writes) - before >= 3  # beats, with no file progress in between
            return []

        with (
            patch.object(Pending, "file_count", return_value=1),
            patch.object(Ocr, "run_phased", side_effect=one_long_step),
        ):
            IndexRunner._run_worker(db_path, None)

        final = IndexRunner.read_state(db_path, raw=True)
        assert final is not None and final.status == "completed"


class TestIndexRun:
    def test_to_dict_has_every_field(self):
        run = index_runner.IndexRun(
            id=3,
            target=None,
            mode="run",
            status="completed",
            pid=9,
            total_files=2,
            processed_files=2,
            failed_files=0,
            workers=1,
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:01:00+00:00",
        )

        assert run.to_dict() == {
            "id": 3,
            "target": None,
            "mode": "run",
            "status": "completed",
            "pid": 9,
            "total_files": 2,
            "processed_files": 2,
            "failed_files": 0,
            "workers": 1,
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
        }


class TestIndexState:
    @pytest.mark.parametrize(
        ("status", "active", "paused", "finished"),
        [
            ("running", True, False, False),
            ("paused", True, True, False),
            ("completed", False, False, True),
            ("stopped", False, False, True),
            ("failed", False, False, True),
        ],
    )
    def test_status_properties(self, status, active, paused, finished):
        state = _state(1, status)

        assert (state.is_active, state.is_paused, state.is_finished) == (active, paused, finished)


class TestSweepStaleTemp:
    def test_removes_temp_from_dead_writer_and_keeps_live_one(self, db_path):
        run_dir = Paths.run_dir(db_path)
        run_dir.mkdir(parents=True, exist_ok=True)
        dead = run_dir / "index_state.json.99999999.1.tmp"
        live = run_dir / f"index_state.json.{os.getpid()}.1.tmp"
        other = run_dir / "notes.txt"
        for file in (dead, live, other):
            file.write_text("x")

        with patch.object(IndexRunner, "_is_pid_running", side_effect=lambda pid: pid != 99999999):
            IndexRunner._sweep_stale_temp(db_path)

        assert not dead.exists()
        assert live.exists()
        assert other.exists()

    def test_missing_run_dir_is_a_no_op(self, tmp_path):
        IndexRunner._sweep_stale_temp(tmp_path / "nowhere" / "vethuq.db")
