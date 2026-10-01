import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    real_connect = db_module.Db.connect
    monkeypatch.setattr(
        db_module.Db,
        "connect",
        staticmethod(lambda path=None, **kwargs: real_connect(db_path, **kwargs)),
    )


def test_gpu_status_disabled_by_default(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "gpu", "status"])

    assert result.exit_code == 0
    assert "disabled" in result.stdout


def test_gpu_enable_then_status(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    enable_result = runner.invoke(app, ["settings", "gpu", "enable"])
    assert enable_result.exit_code == 0

    status_result = runner.invoke(app, ["settings", "gpu", "status"])
    assert "enabled" in status_result.stdout


def test_gpu_enable_then_disable(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    runner.invoke(app, ["settings", "gpu", "enable"])
    disable_result = runner.invoke(app, ["settings", "gpu", "disable"])
    assert disable_result.exit_code == 0

    status_result = runner.invoke(app, ["settings", "gpu", "status"])
    assert "disabled" in status_result.stdout


def test_snippet_show_defaults_to_80(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "search", "snippet", "show"])

    assert result.exit_code == 0
    assert "80" in result.stdout


def test_snippet_set_then_show(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["settings", "search", "snippet", "set", "40"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["settings", "search", "snippet", "show"])
    assert "40" in show_result.stdout


def test_snippet_set_rejects_negative(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "search", "snippet", "set", "--", "-1"])

    assert result.exit_code == 1


def test_export_format_show_defaults_to_json(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "search", "export-format", "show"])

    assert result.exit_code == 0
    assert "json" in result.stdout


def test_export_format_set_then_show(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["settings", "search", "export-format", "set", "html"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["settings", "search", "export-format", "show"])
    assert "html" in show_result.stdout


def test_export_format_set_rejects_unsupported_format(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "search", "export-format", "set", "xml"])

    assert result.exit_code == 1


def test_removed_retention_show_defaults_to_7_days(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "removed-retention", "show"])

    assert result.exit_code == 0
    assert "10080" in result.stdout


def test_removed_retention_set_then_show(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["settings", "index", "removed-retention", "set", "60"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["settings", "index", "removed-retention", "show"])
    assert "60" in show_result.stdout


def test_removed_retention_set_rejects_negative(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "removed-retention", "set", "--", "-1"])

    assert result.exit_code == 1


def test_thread_workers_show_defaults_to_disabled(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "thread-workers", "show"])

    assert result.exit_code == 0
    assert "disabled" in result.stdout


def test_thread_workers_set_then_show(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["settings", "index", "thread-workers", "set", "auto"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["settings", "index", "thread-workers", "show"])
    assert "auto" in show_result.stdout


def test_thread_workers_set_rejects_out_of_range_value(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "thread-workers", "set", "9"])

    assert result.exit_code == 1


def test_stale_lock_show_defaults_to_auto(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "stale-lock", "show"])

    assert result.exit_code == 0
    assert "auto" in result.stdout


def test_stale_lock_set_then_show(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["settings", "index", "stale-lock", "set", "disable"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["settings", "index", "stale-lock", "show"])
    assert "disable" in show_result.stdout


def test_stale_lock_set_rejects_invalid_value(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "stale-lock", "set", "sometimes"])

    assert result.exit_code == 1


def test_engine_show_defaults_to_quick(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "engine", "show"])

    assert result.exit_code == 0
    assert "quick" in result.stdout


def test_engine_set_then_show(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["settings", "index", "engine", "set", "deep"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["settings", "index", "engine", "show"])
    assert "deep" in show_result.stdout


def test_engine_set_rejects_invalid_value(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["settings", "index", "engine", "set", "thorough"])

    assert result.exit_code == 1
