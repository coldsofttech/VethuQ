from datetime import UTC, datetime

import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.index import IndexRunner
from vethuq_core.index import runner as index_runner_module
from vethuq_core.source import Sources

runner = CliRunner()


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _add_pending_source(db_path, tmp_path):
    conn = db_module.Db.connect(db_path)
    try:
        Sources.add(conn, tmp_path)
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

    def test_status_shows_progress(self, use_temp_db):
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

    def test_status_shows_eta_from_processing_metrics(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"fake png bytes")
        (folder / "b.png").write_bytes(b"fake png bytes")

        conn = db_module.Db.connect(db_path)
        Sources.add(conn, folder)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO processing_metrics "
            "(file_type, size_bucket, document_count, avg_duration_seconds, updated_at) "
            "VALUES ('image', 'medium', 3, 10.0, ?)",
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

    def test_status_detail_for_target(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        conn = db_module.Db.connect(db_path)
        Sources.add(conn, folder)
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
