import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from vethuq_core.db import Db
from vethuq_core.index import IndexRunner
from vethuq_core.index import runner as index_runner
from vethuq_core.ocr import Ocr, Pending
from vethuq_core.source import SourceNotFoundError, Sources


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


def _register_source(conn: sqlite3.Connection, tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    Sources.add(conn, folder)


def _fake_run_ocr_phased(
    conn,
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
    def test_run_worker_completes(self, db_path, conn, tmp_path):
        _register_source(conn, tmp_path)
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

    def test_run_worker_stops_when_requested(self, db_path, conn, tmp_path):
        _register_source(conn, tmp_path)
        conn.close()

        def fake_run_ocr_phased(
            conn,
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

    def test_run_worker_pauses_then_resumes(self, db_path, conn, tmp_path, monkeypatch):
        _register_source(conn, tmp_path)
        conn.close()

        calls = {"n": 0}

        def fake_sleep(_seconds: float) -> None:
            calls["n"] += 1
            IndexRunner._set_control(db_path, "run")

        monkeypatch.setattr(index_runner.time, "sleep", fake_sleep)

        def fake_run_ocr_phased(
            conn,
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

    def test_run_worker_restart_passes_only_failed(self, db_path, conn, tmp_path):
        _register_source(conn, tmp_path)
        conn.close()

        seen = {}

        def fake_run_ocr_phased(
            conn,
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

    def test_start_run_redirects_stderr_to_log_file(self, db_path, monkeypatch):
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["stderr"] = kwargs.get("stderr")
            return _FakeProcess(4321)

        monkeypatch.setattr(index_runner.subprocess, "Popen", fake_popen)

        IndexRunner.start_run(None, db_path=db_path)

        assert captured["stderr"] is not None
        assert captured["stderr"] != index_runner.subprocess.DEVNULL
        assert IndexRunner.log_path(db_path).exists()

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

    def test_start_run_raises_on_stale_lock_when_disabled(self, db_path, conn, monkeypatch):
        from vethuq_core.settings import IndexSettings

        IndexSettings.set_stale_lock(conn, "disable")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")

        with pytest.raises(index_runner.StaleLockError):
            IndexRunner.start_run(None, db_path=db_path)

    def test_start_run_force_clears_stale_lock(self, db_path, conn, monkeypatch):
        from vethuq_core.settings import IndexSettings

        IndexSettings.set_stale_lock(conn, "disable")
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

    def test_request_stop_honors_custom_timeout(self, db_path, conn, tmp_path, monkeypatch):
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
        force_kill_calls = []
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

    def test_request_pause_raises_when_not_running(self, db_path):
        with pytest.raises(index_runner.IndexRunnerError):
            IndexRunner.request_pause(db_path=db_path)

    def test_request_resume_raises_when_not_running(self, db_path):
        with pytest.raises(index_runner.IndexRunnerError):
            IndexRunner.request_resume(db_path=db_path)

    def test_request_stop_marks_state_and_history(self, db_path, conn, tmp_path, monkeypatch):
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
