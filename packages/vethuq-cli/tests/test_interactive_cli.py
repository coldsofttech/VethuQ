from functools import partial

import vethuq_cli.settings as settings_module
import vethuq_cli.source as source_module
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    monkeypatch.setattr(source_module, "connect", partial(db_module.connect, db_path))
    monkeypatch.setattr(settings_module, "connect", partial(db_module.connect, db_path))


def test_no_args_shows_banner_and_main_menu(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, [], input="5\n")

    assert result.exit_code == 0
    assert "VethuQ" in result.stdout
    assert "Main Menu" in result.stdout
    assert "Goodbye." in result.stdout


def test_sources_list_then_back_then_exit(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, [], input="2\n1\n0\n5\n")

    assert result.exit_code == 0
    assert "No sources registered yet." in result.stdout


def test_settings_gpu_status_navigation(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, [], input="4\n1\n3\n0\n0\n5\n")

    assert result.exit_code == 0
    assert "GPU: " in result.stdout


def test_invalid_selection_then_quit(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, [], input="9\nq\n")

    assert result.exit_code == 0
    assert "Invalid selection." in result.stdout
    assert "Goodbye." in result.stdout


def test_existing_subcommand_still_works_directly(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["source", "list"])

    assert result.exit_code == 0
    assert "Main Menu" not in result.stdout
