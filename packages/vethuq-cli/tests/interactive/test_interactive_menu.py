from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


class TestInteractiveMenu:
    def test_no_args_shows_banner_and_main_menu(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="8\n")

        assert result.exit_code == 0
        assert "VethuQ" in result.stdout
        assert "Main Menu" in result.stdout
        assert "Goodbye." in result.stdout

    def test_sources_list_then_back_then_exit(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="2\n1\n0\n8\n")

        assert result.exit_code == 0
        assert "No sources registered yet." in result.stdout

    def test_settings_gpu_status_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n1\n3\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "GPU: " in result.stdout

    def test_db_integrity_check_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="6\n1\n0\n8\n")

        assert result.exit_code == 0
        assert "passed" in result.stdout

    def test_settings_db_integrity_check_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n4\n1\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Integrity check: " in result.stdout

    def test_settings_logs_level_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n5\n1\n2\ndebug\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Log level set to debug." in result.stdout
        assert "Log level: debug" in result.stdout

    def test_settings_logs_retention_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n5\n2\n2\n30\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Log retention set to 30 days." in result.stdout
        assert "Log retention: 30 days" in result.stdout

    def test_logs_menu_shows_a_component_log(self, use_temp_db):
        db_path = use_temp_db()
        log_dir = db_path.parent / "logs"
        log_dir.mkdir()
        (log_dir / "index.log").write_text(
            "2026-10-01 10:00:00,000 INFO [MainThread] vethuq.index: hello menu\n",
            encoding="utf-8",
        )

        result = runner.invoke(app, [], input="7\n2\n10\n0\n8\n")

        assert result.exit_code == 0
        assert "hello menu" in result.stdout

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
