from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _unwrapped(output: str) -> str:
    """`output` with the panel borders and the line breaks a long path wraps at removed."""
    return "".join(output.replace("\u2502", " ").split())


class TestSource:
    def test_add_and_list_source(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()

        add_result = runner.invoke(app, ["source", "add", str(folder)])
        assert add_result.exit_code == 0
        assert "Added folder" in add_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert list_result.exit_code == 0
        assert _unwrapped(str(folder.resolve())) in _unwrapped(list_result.stdout)

    def test_add_missing_path_fails(self, use_temp_db, tmp_path):
        use_temp_db()

        result = runner.invoke(app, ["source", "add", str(tmp_path / "missing")])

        assert result.exit_code == 1

    def test_remove_source_with_force_skips_confirmation(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        remove_result = runner.invoke(app, ["source", "remove", str(folder), "--force"])
        assert remove_result.exit_code == 0
        assert "Removed folder" in remove_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert "No sources registered yet." in list_result.stdout

    def test_remove_source_confirms_before_removing(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        remove_result = runner.invoke(app, ["source", "remove", str(folder)], input="y\n")
        assert remove_result.exit_code == 0
        assert "Removed folder" in remove_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert "No sources registered yet." in list_result.stdout

    def test_remove_source_declined_leaves_source_registered(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        remove_result = runner.invoke(app, ["source", "remove", str(folder)], input="n\n")
        assert remove_result.exit_code == 0
        assert "Removed folder" not in remove_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert _unwrapped(str(folder.resolve())) in _unwrapped(list_result.stdout)
