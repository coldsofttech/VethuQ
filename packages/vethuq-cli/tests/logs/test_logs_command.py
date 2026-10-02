from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _entry(level: str, message: str, second: int = 0) -> str:
    return f"2026-10-01 10:00:{second:02d},000 {level} [MainThread] vethuq.index: {message}"


def _write_log(db_path, text: str, suffix: str = "") -> None:
    log_dir = db_path.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / f"index.log{suffix}").write_text(text, encoding="utf-8")


class TestLogsCommand:
    def test_no_component_lists_the_log_files(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["logs"])

        assert result.exit_code == 0
        for component in ("database", "index", "ui", "cli"):
            assert component in result.stdout
        assert "vethuq logs <component>" in result.stdout

    def test_tail_shows_only_the_last_entries(self, use_temp_db):
        db_path = use_temp_db()
        _write_log(db_path, "\n".join(_entry("INFO", f"m{i}", i) for i in range(5)) + "\n")

        result = runner.invoke(app, ["logs", "index", "--tail", "2"])

        assert result.exit_code == 0
        assert "m4" in result.stdout
        assert "m3" in result.stdout
        assert "m2" not in result.stdout

    def test_level_filters_entries(self, use_temp_db):
        db_path = use_temp_db()
        _write_log(db_path, _entry("INFO", "chatty") + "\n" + _entry("ERROR", "boom", 1) + "\n")

        result = runner.invoke(app, ["logs", "index", "--level", "error"])

        assert "boom" in result.stdout
        assert "chatty" not in result.stdout

    def test_date_reads_a_rotated_log(self, use_temp_db):
        db_path = use_temp_db()
        _write_log(db_path, _entry("INFO", "last week") + "\n", suffix=".2026-09-28")

        result = runner.invoke(app, ["logs", "index", "--date", "2026-09-28"])

        assert result.exit_code == 0
        assert "last week" in result.stdout

    def test_export_writes_entries_to_a_file(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _write_log(db_path, _entry("INFO", "keep me") + "\n")
        out = tmp_path / "out.log"

        result = runner.invoke(app, ["logs", "index", "--export", str(out)])

        assert result.exit_code == 0
        assert "keep me" in out.read_text(encoding="utf-8")
        assert "keep me" not in result.stdout

    def test_missing_log_is_an_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["logs", "index"])

        assert result.exit_code == 1

    def test_unknown_component_is_an_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["logs", "nope"])

        assert result.exit_code == 1

    def test_invalid_level_is_an_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["logs", "index", "--level", "loud"])

        assert result.exit_code == 1

    def test_follow_cannot_be_combined_with_export(self, use_temp_db, tmp_path):
        use_temp_db()

        result = runner.invoke(
            app, ["logs", "index", "--follow", "--export", str(tmp_path / "out.log")]
        )

        assert result.exit_code == 1
