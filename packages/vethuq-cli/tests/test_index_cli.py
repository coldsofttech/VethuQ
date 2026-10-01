from datetime import UTC, datetime

import vethuq_cli.index as index_cli_module
import vethuq_core.db as db_module
import vethuq_core.index_runner as index_runner_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.source import Sources

runner = CliRunner()


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    real_connect = db_module.Db.connect
    monkeypatch.setattr(
        db_module.Db,
        "connect",
        staticmethod(lambda path=None, **kwargs: real_connect(db_path, **kwargs)),
    )
    monkeypatch.setattr(db_module.Db, "default_db_path", staticmethod(lambda: db_path))
    return db_path


def _add_pending_source(db_path, tmp_path):
    conn = db_module.Db.connect(db_path)
    try:
        Sources.add(conn, tmp_path)
    finally:
        conn.close()


def test_run_starts_background_process(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _add_pending_source(db_path, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(123))

    result = runner.invoke(app, ["index", "run"])

    assert result.exit_code == 0
    assert "Started background index run (pid 123)" in result.stdout


def test_run_wait_keeps_polling_until_state_appears(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _add_pending_source(db_path, tmp_path)
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
        thread_workers_setting="1",
        workers=1,
        current_files=["a.pdf"],
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
    assert "Status" in result.stdout
    assert "completed" in result.stdout


def test_run_wait_stops_if_process_ends_without_state(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _add_pending_source(db_path, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(888))
    monkeypatch.setattr(index_cli_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(index_cli_module, "read_state", lambda: None)
    monkeypatch.setattr(index_cli_module, "is_running", lambda: (False, None))

    result = runner.invoke(app, ["index", "run", "--wait"])

    assert result.exit_code == 0
    assert "Background run ended before reporting any progress." in result.stdout


def test_run_reports_already_running(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _add_pending_source(db_path, tmp_path)
    index_runner_module._atomic_write(index_runner_module._lock_path(db_path), "999")
    monkeypatch.setattr(index_runner_module, "_is_pid_running", lambda pid: True)

    result = runner.invoke(app, ["index", "run"])

    assert result.exit_code == 1
    assert "already in progress" in result.output


def test_restart_starts_background_process(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _add_pending_source(db_path, tmp_path)
    monkeypatch.setattr(index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(456))

    result = runner.invoke(app, ["index", "restart"])

    assert result.exit_code == 0
    assert "Started background restart (pid 456)" in result.stdout


def test_run_unknown_target_fails(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "run", "999"])

    assert result.exit_code == 1


def test_run_with_no_sources_registered_does_not_start_a_process(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    def _fail_popen(*args, **kwargs):
        raise AssertionError("should not start a background process with no sources registered")

    monkeypatch.setattr(index_runner_module.subprocess, "Popen", _fail_popen)

    result = runner.invoke(app, ["index", "run"])

    assert result.exit_code == 0
    assert "No sources registered yet." in result.stdout
    assert "vethuq source add" in result.stdout


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
        thread_workers_setting="1",
        workers=1,
        current_files=["a.pdf"],
        started_at=now,
        updated_at=now,
    )
    index_runner_module._write_state(db_path, state)

    result = runner.invoke(app, ["index", "status"])

    assert result.exit_code == 0
    assert "1/4" in result.stdout


def test_status_wait_live_refreshes_until_terminal_state(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
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
    index_runner_module._write_state(db_path, running_state)
    monkeypatch.setattr(index_cli_module.time, "sleep", lambda _seconds: None)

    calls = {"n": 0}

    def fake_read_state(db_path=None):
        calls["n"] += 1
        return running_state if calls["n"] == 1 else completed_state

    monkeypatch.setattr(index_cli_module, "read_state", fake_read_state)
    monkeypatch.setattr(index_cli_module, "is_running", lambda: (True, 777))

    result = runner.invoke(app, ["index", "status", "--wait"])

    assert result.exit_code == 0
    assert "Status" in result.stdout
    assert "completed" in result.stdout


def test_status_shows_eta_from_processing_metrics(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
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
    index_runner_module._write_state(db_path, state)

    result = runner.invoke(app, ["index", "status"])

    assert result.exit_code == 0
    # 2 pending images * 10s average = 20s.
    assert "ETA" in result.stdout
    assert "~20s" in result.stdout


def test_status_detail_for_target(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    conn = db_module.Db.connect(db_path)
    Sources.add(conn, folder)
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

    result = runner.invoke(app, ["index", "stop", "--force"])

    assert result.exit_code == 1


def test_stop_declined_does_not_call_request_stop(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "stop"], input="n\n")

    assert result.exit_code == 0
    assert "Index run stopped." not in result.stdout


def test_pause_and_resume_without_running_fail(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    assert runner.invoke(app, ["index", "pause", "--force"]).exit_code == 1
    assert runner.invoke(app, ["index", "resume"]).exit_code == 1


def test_pause_declined_does_not_call_request_pause(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "pause"], input="n\n")

    assert result.exit_code == 0
    assert "Index run paused." not in result.stdout


def test_history_empty(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["index", "history"])

    assert result.exit_code == 0
    assert "No index runs recorded yet." in result.stdout


def test_history_lists_runs(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
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


def test_state_panel_shows_phase_and_a_bar_per_phase(tmp_path, monkeypatch):
    from rich.console import Console
    from vethuq_core.settings import OcrSettings

    db_path = _use_temp_db(monkeypatch, tmp_path)
    conn = db_module.Db.connect(db_path)
    folder = tmp_path / "src"
    folder.mkdir()
    source = Sources.add(conn, folder)
    for index, phase in enumerate((1, 2, 3), start=1):
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
        ).lastrowid
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'image', 'indexed')",
            (source.id, document_id, str(folder / f"{index}.png")),
        )
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence, ocr_phase, ocr_angles) "
            "VALUES (?, 'x', 0.9, ?, '0')",
            (index, phase),
        )
    conn.commit()
    OcrSettings.set_engine(conn, "deep")
    now = datetime.now(UTC).isoformat()
    state = index_runner_module.IndexState(
        run_id=1,
        pid=1,
        target=None,
        mode="run",
        status="running",
        total_files=3,
        processed_files=3,
        failed_files=0,
        thread_workers_setting="0",
        workers=1,
        current_files=[],
        started_at=now,
        updated_at=now,
        phase=2,
    )

    console = Console(width=100, record=True)
    console.print(index_cli_module._build_state_panel(conn, state, animated=False))
    text = console.export_text()
    conn.close()

    assert "moderate (2/3)" in text
    assert "Quick" in text and "3/3 (100%)" in text
    assert "Moderate" in text and "2/3 (67%)" in text
    assert "Deep" in text and "1/3 (33%)" in text


def test_eta_is_estimated_per_phase_from_each_phases_own_history(tmp_path, monkeypatch):
    from vethuq_core.settings import OcrSettings

    db_path = _use_temp_db(monkeypatch, tmp_path)
    conn = db_module.Db.connect(db_path)
    folder = tmp_path / "src"
    folder.mkdir()
    source = Sources.add(conn, folder)
    conn.execute("UPDATE sources SET status = 'indexed' WHERE id = ?", (source.id,))
    # Two indexed image documents, both still waiting on moderate and deep.
    for index in (1, 2):
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
        ).lastrowid
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'image', 'indexed')",
            (source.id, document_id, str(folder / f"{index}.png")),
        )
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence, ocr_phase, ocr_angles) "
            "VALUES (?, 'x', 0.9, 1, '0')",
            (index,),
        )
    # Quick is fast, moderate takes 30s a document; deep has no history yet.
    conn.execute(
        "INSERT INTO processing_metrics VALUES (1, 'image', 'small', 5, 1.0, 10, 5, 'now')"
    )
    conn.execute(
        "INSERT INTO processing_metrics VALUES (2, 'image', 'small', 5, 30.0, 10, 5, 'now')"
    )
    conn.commit()
    OcrSettings.set_engine(conn, "deep")
    now = datetime.now(UTC).isoformat()
    state = index_runner_module.IndexState(
        run_id=1,
        pid=1,
        target=None,
        mode="run",
        status="running",
        total_files=2,
        processed_files=2,
        failed_files=0,
        thread_workers_setting="0",
        workers=1,
        current_files=[],
        started_at=now,
        updated_at=now,
    )

    by_phase = index_cli_module._estimate_phase_seconds(conn, state)
    conn.close()

    # 2 documents x 30s for moderate; nothing for quick (no files pending) or deep (no history).
    assert by_phase == {2: 60.0}
