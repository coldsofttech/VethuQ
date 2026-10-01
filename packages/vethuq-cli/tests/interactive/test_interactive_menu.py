from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


class TestInteractiveMenu:
    def test_no_args_shows_banner_and_main_menu(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="6\n")

        assert result.exit_code == 0
        assert "VethuQ" in result.stdout
        assert "Main Menu" in result.stdout
        assert "Goodbye." in result.stdout

    def test_sources_list_then_back_then_exit(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="2\n1\n0\n6\n")

        assert result.exit_code == 0
        assert "No sources registered yet." in result.stdout

    def test_settings_gpu_status_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n1\n3\n0\n0\n6\n")

        assert result.exit_code == 0
        assert "GPU: " in result.stdout

    def test_invalid_selection_then_quit(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="9\nq\n")

        assert result.exit_code == 0
        assert "Invalid selection." in result.stdout
        assert "Goodbye." in result.stdout

    def test_existing_subcommand_still_works_directly(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["source", "list"])

        assert result.exit_code == 0
        assert "Main Menu" not in result.stdout
