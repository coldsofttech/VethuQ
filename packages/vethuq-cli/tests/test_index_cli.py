from datetime import UTC, datetime
from functools import partial

import vethuq_cli.index as index_cli_module
import vethuq_core.db as db_module
import vethuq_core.index_runner as index_runner_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.sources import add_source

runner = CliRunner()


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    monkeypatch.setattr(index_cli_module, "connect", partial(db_module.connect, db_path))
    monkeypatch.setattr(index_runner_module, "default_db_path", lambda: db_path)
    return db_path


def test_run_starts_background_process(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(123))

    result = runner.invoke(app, ["index", "run"])

    assert result.exit_code == 0
    assert "Started background index run (pid 123)" in result.stdout


def test_run_wait_keeps_polling_until_state_appears(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(777))
    monkeypatch.setattr(index_cli_module.time, "sleep", lambda _seconds: None)

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
        current_file="a.pdf",
        started_at=now,
        updated_at=now,
    )
    calls = {"n": 0}

    def fake_read_state(db_path=None):
        calls["n"] += 1
        return None if calls["n"] == 1 else completed_state

    monkeypatch.setattr(index_cli_module, "read_state", fake_read_state)
    monkeypatch.setattr(index_cli_module, "is_running", lambda: (True, 777))

    result = runner.invoke(app, ["index", "run", "--wait"])

    assert result.exit_code == 0
    assert "Status: completed" in result.stdout


def test_run_wait_stops_if_process_ends_without_state(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(888))
    monkeypatch.setattr(index_cli_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(index_cli_module, "read_state", lambda: None)
    monkeypatch.setattr(index_cli_module, "is_running", lambda: (False, None))

    result = runner.invoke(app, ["index", "run", "--wait"])

    assert result.exit_code == 0
    assert "Background run ended before reporting any progress." in result.stdout


def test_run_reports_already_running(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    index_runner_module._atomic_write(index_runner_module._lock_path(db_path), "999")
    monkeypatch.setattr(index_runner_module, "_is_pid_running", lambda pid: True)

    result = runner.invoke(app, ["index", "run"])

    assert result.exit_code == 1
    assert "already in progress" in result.output


def test_restart_starts_background_process(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(456))

    result = runner.invoke(app, ["index", "restart"])

    assert result.exit_code == 0
    assert "Started background restart (pid 456)" in result.stdout


def test_run_unknown_target_fails(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "run", "999"])

    assert result.exit_code == 1


def test_status_with_no_run(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "status"])

    assert result.exit_code == 0
    assert "No index run has been started yet." in result.stdout


def test_status_shows_progress(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
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
        current_file="a.pdf",
        started_at=now,
        updated_at=now,
    )
    index_runner_module._write_state(db_path, state)

    result = runner.invoke(app, ["index", "status"])

    assert result.exit_code == 0
    assert "1/4" in result.stdout


def test_status_detail_for_target(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    conn = db_module.connect(db_path)
    add_source(conn, folder)
    conn.close()

    result = runner.invoke(app, ["index", "status", str(folder)])

    assert result.exit_code == 0
    assert "No files indexed yet for this source." in result.stdout


def test_status_unknown_target_fails(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "status", "999"])

    assert result.exit_code == 1


def test_stop_without_running_fails(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "stop"])

    assert result.exit_code == 1


def test_pause_and_resume_without_running_fail(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    assert runner.invoke(app, ["index", "pause"]).exit_code == 1
    assert runner.invoke(app, ["index", "resume"]).exit_code == 1


def test_history_empty(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "history"])

    assert result.exit_code == 0
    assert "No index runs recorded yet." in result.stdout


def test_history_lists_runs(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    conn = db_module.connect(db_path)
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
