from functools import partial

import vethuq_cli.settings as settings_module
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    monkeypatch.setattr(settings_module, "connect", partial(db_module.connect, db_path))


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
