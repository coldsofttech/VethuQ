from functools import partial

import vethuq_cli.source as source_module
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    monkeypatch.setattr(source_module, "connect", partial(db_module.connect, db_path))


def test_add_and_list_source(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()

    add_result = runner.invoke(app, ["source", "add", str(folder)])
    assert add_result.exit_code == 0
    assert "Added folder" in add_result.stdout

    list_result = runner.invoke(app, ["source", "list"])
    assert list_result.exit_code == 0
    assert str(folder.resolve()) in list_result.stdout


def test_add_missing_path_fails(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["source", "add", str(tmp_path / "missing")])

    assert result.exit_code == 1


def test_remove_source(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    runner.invoke(app, ["source", "add", str(folder)])

    remove_result = runner.invoke(app, ["source", "remove", str(folder)])
    assert remove_result.exit_code == 0
    assert "Removed folder" in remove_result.stdout

    list_result = runner.invoke(app, ["source", "list"])
    assert "No sources registered yet." in list_result.stdout
