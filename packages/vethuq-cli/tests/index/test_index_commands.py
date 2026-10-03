import re
from datetime import UTC, datetime

import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.index import IndexRunner
from vethuq_core.index import runner as index_runner_module
from vethuq_core.sources import Sources
from vethuq_core.storage.sqlite import SqliteStorage

runner = CliRunner()


def _flatten(output: str) -> str:
    """Collapse the panel's border and wrapped, colour-coded text back onto one plain line."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(plain.replace("\u2502", " ").split())


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _add_pending_source(db_path, tmp_path):
    conn = db_module.Db.connect(db_path)
    try:
        Sources.add(SqliteStorage(conn), tmp_path)
    finally:
        conn.close()


def _patch_polling(monkeypatch, *, read_state, is_running):
    """Fake what the CLI's no-argument polling sees, leaving calls that pass a db_path real."""
    real_read_state = IndexRunner.read_state
    real_is_running = IndexRunner.is_running
    monkeypatch.setattr(
        IndexRunner,
        "read_state",
        lambda db_path=None: real_read_state(db_path) if db_path is not None else read_state(),
    )
    monkeypatch.setattr(
        IndexRunner,
        "is_running",
        lambda db_path=None: real_is_running(db_path) if db_path is not None else is_running(),
    )


class TestRun:
    def test_run_starts_background_process(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(123)
        )

        result = runner.invoke(app, ["index", "run"])

        assert result.exit_code == 0
        assert "Started background index run (pid 123)" in result.stdout
        assert "Recovered from" not in result.stdout

    def test_run_reports_recovery_after_stale_lock(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(123)
        )

        result = runner.invoke(app, ["index", "run"])

        assert result.exit_code == 0
        assert "Recovered from a previous run" in result.stdout
        assert "Started background index run (pid 123)" in result.stdout

    def test_run_wait_keeps_polling_until_state_appears(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(777)
        )
        monkeypatch.setattr(index_runner_module.time, "sleep", lambda _seconds: None)

        now = datetime.now(UTC).isoformat()
        completed_state = index_runner_module.IndexState(
            run_id=1,
            pid=777,
            target=None,
            mode="run",
            status="completed",
            total_files=1,
            processed_files=1,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=["a.pdf"],
            started_at=now,
            updated_at=now,
        )
        calls = {"n": 0}

        def fake_read_state():
            calls["n"] += 1
            return None if calls["n"] == 1 else completed_state

        _patch_polling(monkeypatch, read_state=fake_read_state, is_running=lambda: (True, 777))

        result = runner.invoke(app, ["index", "run", "--wait"])

        assert result.exit_code == 0
        assert "Status" in result.stdout
        assert "completed" in result.stdout

    def test_run_wait_stops_if_process_ends_without_state(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(888)
        )
        monkeypatch.setattr(index_runner_module.time, "sleep", lambda _seconds: None)
        _patch_polling(
            monkeypatch, read_state=lambda db_path=None: None, is_running=lambda: (False, None)
        )

        result = runner.invoke(app, ["index", "run", "--wait"])

        assert result.exit_code == 0
        assert "Background run ended before reporting any progress." in result.stdout

    def test_run_wait_ctrl_c_stops_the_run(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(555)
        )

        def interrupted_wait(*_args, **_kwargs):
            raise KeyboardInterrupt

        stops = []
        monkeypatch.setattr(IndexRunner, "wait", interrupted_wait)
        monkeypatch.setattr(IndexRunner, "request_stop", lambda: stops.append(True))

        result = runner.invoke(app, ["index", "run", "--wait"])

        assert result.exit_code == 130
        assert stops == [True]
        assert "Interrupted" in _flatten(result.stdout)

    def test_status_wait_ctrl_c_does_not_stop_the_run(self, use_temp_db, monkeypatch):
        use_temp_db()
        now = datetime.now(UTC).isoformat()
        running_state = index_runner_module.IndexState(
            run_id=1,
            pid=556,
            target=None,
            mode="run",
            status="running",
            total_files=1,
            processed_files=0,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=["a.pdf"],
            started_at=now,
            updated_at=now,
        )
        monkeypatch.setattr(IndexRunner, "read_state", lambda db_path=None: running_state)

        def interrupted_wait(*_args, **_kwargs):
            raise KeyboardInterrupt

        stops = []
        monkeypatch.setattr(IndexRunner, "wait", interrupted_wait)
        monkeypatch.setattr(IndexRunner, "request_stop", lambda: stops.append(True))

        runner.invoke(app, ["index", "status", "--wait"])

        assert stops == []

    def test_run_reports_already_running(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)

        result = runner.invoke(app, ["index", "run"])

        assert result.exit_code == 1
        assert "already in progress" in result.output

    def test_run_unknown_target_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "run", "999"])

        assert result.exit_code == 1

    def test_run_with_no_sources_registered_does_not_start_a_process(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        use_temp_db()

        def _fail_popen(*args, **kwargs):
            raise AssertionError("should not start a background process with no sources registered")

        monkeypatch.setattr(index_runner_module.subprocess, "Popen", _fail_popen)

        result = runner.invoke(app, ["index", "run"])

        assert result.exit_code == 0
        assert "No sources registered yet." in result.stdout
        assert "vethuq source add" in result.stdout


class TestRestart:
    def test_restart_starts_background_process(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _add_pending_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(456)
        )

        result = runner.invoke(app, ["index", "restart"])

        assert result.exit_code == 0
        assert "Started background restart (pid 456)" in result.stdout


class TestStatus:
    def test_status_with_no_run(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "status"])

        assert result.exit_code == 0
        assert "No index run has been started yet." in result.stdout

    def test_status_shows_progress(self, use_temp_db, monkeypatch):
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        db_path = use_temp_db()
        now = datetime.now(UTC).isoformat()
        state = index_runner_module.IndexState(
            run_id=1,
            pid=1,
            target=None,
            mode="run",
            status="running",
            total_files=4,
            processed_files=1,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=["a.pdf"],
            started_at=now,
            updated_at=now,
        )
        IndexRunner._write_state(db_path, state)

        result = runner.invoke(app, ["index", "status"])

        assert result.exit_code == 0
        assert "1/4" in result.stdout

    def test_status_wait_live_refreshes_until_terminal_state(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        db_path = use_temp_db()
        now = datetime.now(UTC).isoformat()
        running_state = index_runner_module.IndexState(
            run_id=1,
            pid=777,
            target=None,
            mode="run",
            status="running",
            total_files=4,
            processed_files=1,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=["a.pdf"],
            started_at=now,
            updated_at=now,
        )
        completed_state = index_runner_module.IndexState(
            run_id=1,
            pid=777,
            target=None,
            mode="run",
            status="completed",
            total_files=4,
            processed_files=4,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=[],
            started_at=now,
            updated_at=now,
        )
        IndexRunner._write_state(db_path, running_state)
        monkeypatch.setattr(index_runner_module.time, "sleep", lambda _seconds: None)

        calls = {"n": 0}

        def fake_read_state():
            calls["n"] += 1
            return running_state if calls["n"] == 1 else completed_state

        _patch_polling(monkeypatch, read_state=fake_read_state, is_running=lambda: (True, 777))

        result = runner.invoke(app, ["index", "status", "--wait"])

        assert result.exit_code == 0
        assert "Status" in result.stdout
        assert "completed" in result.stdout

    def test_status_shows_eta_from_processing_metrics(self, use_temp_db, tmp_path, monkeypatch):
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"fake png bytes")
        (folder / "b.png").write_bytes(b"fake png bytes")

        conn = db_module.Db.connect(db_path)
        Sources.add(SqliteStorage(conn), folder)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO processing_metrics "
            "(file_type, extension, size_bucket, document_count, avg_duration_seconds, "
            "updated_at) VALUES ('image', 'png', 'medium', 3, 10.0, ?)",
            (now,),
        )
        conn.commit()
        conn.close()

        state = index_runner_module.IndexState(
            run_id=1,
            pid=1,
            target=str(folder),
            mode="run",
            status="running",
            total_files=2,
            processed_files=0,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=[],
            started_at=now,
            updated_at=now,
        )
        IndexRunner._write_state(db_path, state)

        result = runner.invoke(app, ["index", "status"])

        assert result.exit_code == 0
        # 2 pending images * 10s average = 20s.
        assert "ETA" in result.stdout
        assert "~20s" in result.stdout

    def test_status_reports_a_dead_worker_as_failed_not_running(self, use_temp_db, monkeypatch):
        db_path = use_temp_db()
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        now = datetime.now(UTC).isoformat()
        IndexRunner._write_state(
            db_path,
            index_runner_module.IndexState(
                run_id=1,
                pid=1,
                target=None,
                mode="run",
                status="running",
                total_files=2,
                processed_files=1,
                failed_files=0,
                thread_workers_setting="1",
                workers=1,
                current_files=["a.png"],
                started_at=now,
                updated_at=now,
            ),
        )

        result = runner.invoke(app, ["index", "status"])

        assert result.exit_code == 0
        assert "failed" in result.stdout
        assert "exited unexpectedly" in _flatten(result.stdout)
        assert "running" not in result.stdout

    def test_status_warns_when_a_live_worker_has_gone_quiet(self, use_temp_db, monkeypatch):
        db_path = use_temp_db()
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        now = datetime.now(UTC).isoformat()
        state = index_runner_module.IndexState(
            run_id=1,
            pid=1,
            target=None,
            mode="run",
            status="running",
            total_files=2,
            processed_files=1,
            failed_files=0,
            thread_workers_setting="1",
            workers=1,
            current_files=[],
            started_at=now,
            updated_at=now,
        )
        IndexRunner._write_state(db_path, state)
        quiet = IndexRunner._state_path(db_path)
        quiet.write_text(
            quiet.read_text(encoding="utf-8").replace(
                state.updated_at, "2000-01-01T00:00:00+00:00"
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["index", "status"])

        assert "may be hung" in _flatten(result.stdout)

    def test_status_detail_for_target(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        conn = db_module.Db.connect(db_path)
        Sources.add(SqliteStorage(conn), folder)
        conn.close()

        result = runner.invoke(app, ["index", "status", str(folder)])

        assert result.exit_code == 0
        assert "No files indexed yet for this source." in result.stdout

    def test_status_unknown_target_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "status", "999"])

        assert result.exit_code == 1


class TestStopAndPause:
    def test_stop_without_running_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "stop", "--force"])

        assert result.exit_code == 1

    def test_stop_declined_does_not_call_request_stop(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "stop"], input="n\n")

        assert result.exit_code == 0
        assert "Index run stopped." not in result.stdout

    def test_pause_and_resume_without_running_fail(self, use_temp_db):
        use_temp_db()

        assert runner.invoke(app, ["index", "pause", "--force"]).exit_code == 1
        assert runner.invoke(app, ["index", "resume"]).exit_code == 1

    def test_pause_declined_does_not_call_request_pause(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "pause"], input="n\n")

        assert result.exit_code == 0
        assert "Index run paused." not in result.stdout


class TestHistory:
    def test_history_empty(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "history"])

        assert result.exit_code == 0
        assert "No index runs recorded yet." in result.stdout

    def test_history_lists_runs(self, use_temp_db):
        db_path = use_temp_db()
        conn = db_module.Db.connect(db_path)
        conn.execute(
            "INSERT INTO index_runs (target, status, pid, total_files, processed_files, "
            "failed_files, started_at) VALUES (NULL, 'completed', 1, 3, 3, 0, ?)",
            (datetime.now(UTC).isoformat(),),
        )
        conn.commit()
        conn.close()

        result = runner.invoke(app, ["index", "history"])

        assert result.exit_code == 0
        assert "completed" in result.stdout
