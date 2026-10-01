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


def test_remove_source_with_force_skips_confirmation(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    runner.invoke(app, ["source", "add", str(folder)])

    remove_result = runner.invoke(app, ["source", "remove", str(folder), "--force"])
    assert remove_result.exit_code == 0
    assert "Removed folder" in remove_result.stdout

    list_result = runner.invoke(app, ["source", "list"])
    assert "No sources registered yet." in list_result.stdout


def test_remove_source_confirms_before_removing(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    runner.invoke(app, ["source", "add", str(folder)])

    remove_result = runner.invoke(app, ["source", "remove", str(folder)], input="y\n")
    assert remove_result.exit_code == 0
    assert "Removed folder" in remove_result.stdout

    list_result = runner.invoke(app, ["source", "list"])
    assert "No sources registered yet." in list_result.stdout


def test_remove_source_declined_leaves_source_registered(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    folder = tmp_path / "docs"
    folder.mkdir()
    runner.invoke(app, ["source", "add", str(folder)])

    remove_result = runner.invoke(app, ["source", "remove", str(folder)], input="n\n")
    assert remove_result.exit_code == 0
    assert "Removed folder" not in remove_result.stdout

    list_result = runner.invoke(app, ["source", "list"])
    assert str(folder.resolve()) in list_result.stdout
