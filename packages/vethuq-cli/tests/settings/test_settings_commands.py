import re

from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.db.backup import Backup
from vethuq_core.storage import open_storage

runner = CliRunner()


class TestGpu:
    def test_gpu_status_disabled_by_default(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "gpu", "status"])

        assert result.exit_code == 0
        assert "disabled" in result.stdout

    def test_gpu_enable_then_status(self, use_temp_db):
        use_temp_db()

        enable_result = runner.invoke(app, ["settings", "gpu", "enable"])
        assert enable_result.exit_code == 0

        status_result = runner.invoke(app, ["settings", "gpu", "status"])
        assert "enabled" in status_result.stdout

    def test_gpu_enable_then_disable(self, use_temp_db):
        use_temp_db()

        runner.invoke(app, ["settings", "gpu", "enable"])
        disable_result = runner.invoke(app, ["settings", "gpu", "disable"])
        assert disable_result.exit_code == 0

        status_result = runner.invoke(app, ["settings", "gpu", "status"])
        assert "disabled" in status_result.stdout


class TestSnippet:
    def test_snippet_show_defaults_to_80(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "snippet", "show"])

        assert result.exit_code == 0
        assert "80" in result.stdout

    def test_snippet_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "search", "snippet", "set", "40"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "search", "snippet", "show"])
        assert "40" in show_result.stdout

    def test_snippet_set_rejects_negative(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "snippet", "set", "--", "-1"])

        assert result.exit_code == 1


class TestExportFormat:
    def test_export_format_show_defaults_to_json(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "export-format", "show"])

        assert result.exit_code == 0
        assert "json" in result.stdout

    def test_export_format_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "search", "export-format", "set", "html"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "search", "export-format", "show"])
        assert "html" in show_result.stdout

    def test_export_format_set_rejects_unsupported_format(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "export-format", "set", "xml"])

        assert result.exit_code == 1


class TestRemovedRetention:
    def test_removed_retention_show_defaults_to_7_days(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "removed-retention", "show"])

        assert result.exit_code == 0
        assert "10080" in result.stdout

    def test_removed_retention_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "index", "removed-retention", "set", "60"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "index", "removed-retention", "show"])
        assert "60" in show_result.stdout

    def test_removed_retention_set_rejects_negative(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "removed-retention", "set", "--", "-1"])

        assert result.exit_code == 1


class TestThreadWorkers:
    def test_thread_workers_show_defaults_to_disabled(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "thread-workers", "show"])

        assert result.exit_code == 0
        assert "disabled" in result.stdout

    def test_thread_workers_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "index", "thread-workers", "set", "auto"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "index", "thread-workers", "show"])
        assert "auto" in show_result.stdout

    def test_thread_workers_set_rejects_out_of_range_value(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "thread-workers", "set", "9"])

        assert result.exit_code == 1


class TestStaleLock:
    def test_stale_lock_show_defaults_to_auto(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "stale-lock", "show"])

        assert result.exit_code == 0
        assert "auto" in result.stdout

    def test_stale_lock_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "index", "stale-lock", "set", "disable"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "index", "stale-lock", "show"])
        assert "disable" in show_result.stdout

    def test_stale_lock_set_rejects_invalid_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "stale-lock", "set", "sometimes"])

        assert result.exit_code == 1


class TestIntegrityCheck:
    def test_integrity_check_show_defaults_to_auto(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "db", "integrity-check", "show"])

        assert result.exit_code == 0
        assert "auto" in result.stdout

    def test_integrity_check_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "db", "integrity-check", "set", "disable"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "db", "integrity-check", "show"])
        assert "disable" in show_result.stdout

    def test_integrity_check_set_rejects_invalid_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "db", "integrity-check", "set", "sometimes"])

        assert result.exit_code == 1

    def test_integrity_check_interval_show_defaults_to_one_day(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "db", "integrity-check", "interval", "show"])

        assert result.exit_code == 0
        assert "1440" in result.stdout

    def test_integrity_check_interval_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(
            app, ["settings", "db", "integrity-check", "interval", "set", "60"]
        )
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "db", "integrity-check", "interval", "show"])
        assert "60" in show_result.stdout

    def test_integrity_check_interval_set_rejects_negative(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(
            app, ["settings", "db", "integrity-check", "interval", "set", "--", "-1"]
        )

        assert result.exit_code == 1


class TestEngine:
    def test_engine_show_defaults_to_quick(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "ocr", "engine", "show"])

        assert result.exit_code == 0
        assert "quick" in result.stdout

    def test_engine_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "ocr", "engine", "set", "deep"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "ocr", "engine", "show"])
        assert "deep" in show_result.stdout

    def test_engine_set_rejects_invalid_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "ocr", "engine", "set", "thorough"])

        assert result.exit_code == 1


class TestLogs:
    def test_level_show_defaults_to_info(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "logs", "level", "show"])

        assert result.exit_code == 0
        assert "info" in result.stdout

    def test_level_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "logs", "level", "set", "debug"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "logs", "level", "show"])
        assert "debug" in show_result.stdout

    def test_level_set_rejects_invalid_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "logs", "level", "set", "loud"])

        assert result.exit_code == 1

    def test_retention_defaults_to_15_days(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "logs", "retention", "show"])

        assert result.exit_code == 0
        assert "15 days" in result.stdout

    def test_retention_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "logs", "retention", "set", "7"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "logs", "retention", "show"])
        assert "7 days" in show_result.stdout

    def test_retention_set_rejects_zero(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "logs", "retention", "set", "0"])

        assert result.exit_code == 1


class TestStabilityCheck:
    def test_stability_check_defaults_then_set(self, use_temp_db):
        use_temp_db()

        show = runner.invoke(app, ["settings", "index", "stability-check", "show"])
        assert "Stability check" in show.stdout
        set_result = runner.invoke(app, ["settings", "index", "stability-check", "set", "0.5"])
        assert set_result.exit_code == 0
        show = runner.invoke(app, ["settings", "index", "stability-check", "show"])
        assert "0.5" in show.stdout

    def test_stability_check_rejects_negative(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "stability-check", "set", "--", "-1"])

        assert result.exit_code == 1


class TestSearchEngineSettings:
    def test_engine_show_defaults_to_all(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "engine", "show"])

        assert result.exit_code == 0
        assert "all" in result.stdout

    def test_engine_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "search", "engine", "set", "full-text"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "search", "engine", "show"])
        assert "full-text" in show_result.stdout

    def test_engine_set_rejects_unknown_engine(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "engine", "set", "nope"])

        assert result.exit_code == 1

    def test_case_sensitive_show_enable_disable(self, use_temp_db):
        use_temp_db()
        show = ["settings", "search", "case-sensitive", "show"]

        assert "disabled" in runner.invoke(app, show).stdout
        assert runner.invoke(app, ["settings", "search", "case-sensitive", "enable"]).exit_code == 0
        assert "enabled" in runner.invoke(app, show).stdout
        assert (
            runner.invoke(app, ["settings", "search", "case-sensitive", "disable"]).exit_code == 0
        )
        assert "disabled" in runner.invoke(app, show).stdout

    def test_fuzzy_threshold_show_defaults_to_balanced(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "show"])

        assert result.exit_code == 0
        assert "balanced" in result.stdout
        assert "80%" in result.stdout

    def test_fuzzy_threshold_set_preset_and_number_then_show(self, use_temp_db):
        use_temp_db()
        show = ["settings", "search", "fuzzy", "threshold", "show"]

        loose = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "set", "loose"])
        assert loose.exit_code == 0
        shown = runner.invoke(app, show)
        assert "loose" in shown.stdout and "65%" in shown.stdout

        number = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "set", "0.75"])
        assert number.exit_code == 0
        assert "0.75" in runner.invoke(app, show).stdout

    def test_fuzzy_threshold_set_rejects_invalid_values(self, use_temp_db):
        use_temp_db()

        for value in ("nope", "0", "1.5"):
            result = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "set", value])
            assert result.exit_code == 1

        shown = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "show"])
        assert "balanced" in shown.stdout

    def test_fuzzy_threshold_set_accepts_a_percentage(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "set", "75%"])
        shown = runner.invoke(app, ["settings", "search", "fuzzy", "threshold", "show"])

        assert result.exit_code == 0
        assert "75%" in shown.stdout

    def test_proximity_distance_show_defaults_to_medium(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "proximity", "distance", "show"])

        assert result.exit_code == 0
        assert "medium" in result.stdout and "10 words" in result.stdout

    def test_proximity_distance_set_preset_and_number_then_show(self, use_temp_db):
        use_temp_db()
        show = ["settings", "search", "proximity", "distance", "show"]

        loose = runner.invoke(app, ["settings", "search", "proximity", "distance", "set", "loose"])
        assert loose.exit_code == 0
        shown = runner.invoke(app, show)
        assert "loose" in shown.stdout and "30 words" in shown.stdout

        number = runner.invoke(app, ["settings", "search", "proximity", "distance", "set", "15"])
        assert number.exit_code == 0
        assert "15 words" in runner.invoke(app, show).stdout

    def test_proximity_distance_set_rejects_invalid_values(self, use_temp_db):
        use_temp_db()

        for value in ("nope", "0", "101", "2.5"):
            result = runner.invoke(
                app, ["settings", "search", "proximity", "distance", "set", value]
            )
            assert result.exit_code == 1

        shown = runner.invoke(app, ["settings", "search", "proximity", "distance", "show"])
        assert "medium" in shown.stdout


class TestNormalizeSettings:
    def test_show_defaults_to_auto(self, use_temp_db):
        use_temp_db()

        case = runner.invoke(app, ["settings", "search", "normalize", "case", "show"])
        leetspeak = runner.invoke(app, ["settings", "search", "normalize", "leetspeak", "show"])

        assert case.exit_code == 0 and "auto" in case.stdout
        assert leetspeak.exit_code == 0 and "auto" in leetspeak.stdout

    def test_set_then_show(self, use_temp_db):
        use_temp_db()

        for name, values in (
            ("case", ("match", "ignore", "Auto")),
            ("leetspeak", ("off", "standard", "extended", "Basic", "auto")),
        ):
            for value in values:
                set_result = runner.invoke(
                    app, ["settings", "search", "normalize", name, "set", value]
                )
                shown = runner.invoke(app, ["settings", "search", "normalize", name, "show"])
                assert set_result.exit_code == 0
                assert f"set to {value.lower()}" in set_result.stdout
                assert value.lower() in shown.stdout

    def test_set_rejects_unknown_values(self, use_temp_db):
        use_temp_db()

        case = runner.invoke(app, ["settings", "search", "normalize", "case", "set", "sometimes"])
        leetspeak = runner.invoke(
            app, ["settings", "search", "normalize", "leetspeak", "set", "insane"]
        )

        assert case.exit_code == 1 and "ignore, match" in case.output
        assert leetspeak.exit_code == 1 and "off, basic, standard, extended" in leetspeak.output
        shown = runner.invoke(app, ["settings", "search", "normalize", "leetspeak", "show"])
        assert "auto" in shown.stdout

    def test_the_case_sensitive_commands_are_the_same_setting(self, use_temp_db):
        use_temp_db()

        runner.invoke(app, ["settings", "search", "case-sensitive", "enable"])
        assert (
            "match"
            in runner.invoke(app, ["settings", "search", "normalize", "case", "show"]).stdout
        )

        runner.invoke(app, ["settings", "search", "normalize", "case", "set", "ignore"])
        assert (
            "disabled"
            in runner.invoke(app, ["settings", "search", "case-sensitive", "show"]).stdout
        )

        runner.invoke(app, ["settings", "search", "normalize", "case", "set", "match"])
        assert (
            "enabled" in runner.invoke(app, ["settings", "search", "case-sensitive", "show"]).stdout
        )

    def test_the_old_leetspeak_level_command_is_gone(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "leetspeak", "level", "show"])

        assert result.exit_code != 0

    def test_leetspeak_is_not_an_engine(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "engine", "set", "leetspeak"])

        assert result.exit_code == 1


class TestNoiseLevel:
    def test_show_defaults_to_low(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "noise-fuzzy", "noise", "show"])

        assert result.exit_code == 0
        assert "low" in result.stdout and "1 in a row, 2 in all" in result.stdout

    def test_set_then_show(self, use_temp_db):
        use_temp_db()
        show = ["settings", "search", "noise-fuzzy", "noise", "show"]

        for level, limits in (
            ("medium", "3 in a row, 6"),
            ("high", "6 in a row, 12"),
            ("Low", "1"),
        ):
            result = runner.invoke(
                app, ["settings", "search", "noise-fuzzy", "noise", "set", level]
            )
            assert result.exit_code == 0
            assert f"set to {level.lower()}" in result.stdout
            shown = runner.invoke(app, show).stdout
            assert level.lower() in shown and limits in shown

    def test_set_rejects_an_unknown_level(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "search", "noise-fuzzy", "noise", "set", "loud"])
        shown = runner.invoke(app, ["settings", "search", "noise-fuzzy", "noise", "show"])

        assert result.exit_code == 1
        assert "low, medium, high" in result.output
        assert "low" in shown.stdout

    def test_engine_can_be_the_default(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "search", "engine", "set", "noise-fuzzy"])
        shown = runner.invoke(app, ["settings", "search", "engine", "show"])

        assert set_result.exit_code == 0
        assert "noise-fuzzy" in shown.stdout


class TestBackupSettings:
    def test_defaults(self, use_temp_db):
        use_temp_db()

        assert "enable" in runner.invoke(app, ["settings", "db", "backup", "show"]).stdout
        assert "1440" in runner.invoke(app, ["settings", "db", "backup", "interval", "show"]).stdout
        assert "7" in runner.invoke(app, ["settings", "db", "backup", "retention", "show"]).stdout

    def test_set_then_show(self, use_temp_db):
        use_temp_db()

        assert runner.invoke(app, ["settings", "db", "backup", "set", "disable"]).exit_code == 0
        assert (
            runner.invoke(app, ["settings", "db", "backup", "interval", "set", "60"]).exit_code == 0
        )
        assert (
            runner.invoke(app, ["settings", "db", "backup", "retention", "set", "14"]).exit_code
            == 0
        )

        assert "disable" in runner.invoke(app, ["settings", "db", "backup", "show"]).stdout
        assert "60" in runner.invoke(app, ["settings", "db", "backup", "interval", "show"]).stdout
        assert "14" in runner.invoke(app, ["settings", "db", "backup", "retention", "show"]).stdout

    def test_rejects_invalid_values(self, use_temp_db):
        use_temp_db()

        for args in (["set", "auto"], ["interval", "set", "0"], ["retention", "set", "0"]):
            assert runner.invoke(app, ["settings", "db", "backup", *args]).exit_code == 1


def _flat(text: str) -> str:
    """Panel output with borders and whitespace removed, so a long path folded across lines
    still matches."""
    return re.sub(r"[│\s]", "", text)


class TestBackupsLocation:
    def test_show_defaults_to_next_to_the_database(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "location", "backups", "show"])

        assert result.exit_code == 0
        assert "backups" in _flat(result.stdout)
        assert "thedefault" in _flat(result.stdout)

    def test_set_moves_backups_and_show_reflects_it(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        open_storage().close()
        Backup.create(db_path, "keep")
        target = tmp_path / "elsewhere"

        set_result = runner.invoke(
            app, ["settings", "location", "backups", "set", str(target), "--force"]
        )
        show_result = runner.invoke(app, ["settings", "location", "backups", "show"])

        assert set_result.exit_code == 0
        assert (target / "keep.db.gz").exists()
        assert "elsewhere" in _flat(show_result.stdout)

    def test_set_asks_first(self, use_temp_db, tmp_path):
        use_temp_db()
        open_storage().close()

        result = runner.invoke(
            app, ["settings", "location", "backups", "set", str(tmp_path / "x")], input="n\n"
        )

        assert result.exit_code == 1
        assert not (tmp_path / "x").exists()

    def test_reset_returns_to_the_default(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        open_storage().close()
        runner.invoke(
            app,
            ["settings", "location", "backups", "set", str(tmp_path / "elsewhere"), "--force"],
        )

        result = runner.invoke(app, ["settings", "location", "backups", "reset"])

        assert result.exit_code == 0
        assert Backup.directory(db_path) == db_path.parent / "backups"
