from rich.console import Console
from typer.testing import CliRunner
from vethuq_cli.logs import LogsCommand
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


class TestFollowView:
    @staticmethod
    def _render(view, width=60, height=8) -> str:
        console = Console(width=width, height=height, record=True, force_terminal=False)
        console.print(view)
        return console.export_text()

    def test_shows_the_newest_entries_that_fit_the_height(self):
        view = LogsCommand._FollowView(
            "Index Log", [_entry("INFO", f"entry {i}", i) for i in range(20)]
        )

        output = self._render(view, height=8)

        assert "entry 19" in output
        assert "entry 0" not in output
        assert output.count("entry ") <= 6  # 8 rows less the panel's top and bottom

    def test_new_entries_appear_and_old_ones_scroll_off(self):
        view = LogsCommand._FollowView("Index Log", [_entry("INFO", "first", 1)])
        assert "first" in self._render(view)

        for second in range(2, 12):
            view.add(_entry("INFO", f"later {second}", second))
        output = self._render(view, height=6)

        assert "later 11" in output
        assert "first" not in output

    def test_waits_when_there_are_no_entries_yet(self):
        output = self._render(LogsCommand._FollowView("Index Log"))

        assert "Waiting for new log entries" in output
        assert "Index Log" in output


class TestStructuredExport:
    def _log(self, use_temp_db):
        db_path = use_temp_db()
        _write_log(
            db_path,
            _entry("INFO", "scan done: été 日本")
            + "\n"
            + _entry("ERROR", "boom")
            + "\nTraceback (most recent call last):\n  File x\nValueError: bad\n",
        )

    def test_json_splits_each_entry_into_fields(self, use_temp_db, tmp_path):
        import json

        self._log(use_temp_db)
        out = tmp_path / "out.json"

        result = runner.invoke(app, ["logs", "index", "--export", str(out), "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["count"] == 2
        first, second = data["entries"]
        assert first["level"] == "info" and "été 日本" in first["message"]
        assert second["level"] == "error" and "Traceback" in second["message"]
        assert first["time"] and first["logger"]

    def test_html_is_a_table_with_level_pills(self, use_temp_db, tmp_path):
        self._log(use_temp_db)
        out = tmp_path / "out.html"

        result = runner.invoke(app, ["logs", "index", "--export", str(out), "--format", "html"])

        assert result.exit_code == 0
        text = out.read_text(encoding="utf-8")
        assert 'class="pill bad"' in text and 'class="msg"' in text
        assert "été 日本" in text and "ValueError: bad" in text

    def test_text_stays_the_default(self, use_temp_db, tmp_path):
        self._log(use_temp_db)
        out = tmp_path / "out.log"

        runner.invoke(app, ["logs", "index", "--export", str(out), "--format", "text"])

        assert out.read_text(encoding="utf-8").startswith("20")

    def test_an_unknown_format_is_refused(self, use_temp_db, tmp_path):
        self._log(use_temp_db)

        result = runner.invoke(
            app, ["logs", "index", "--export", str(tmp_path / "x"), "--format", "csv"]
        )

        assert result.exit_code == 1

    def test_format_needs_export(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["logs", "index", "--format", "json"])

        assert result.exit_code == 1
