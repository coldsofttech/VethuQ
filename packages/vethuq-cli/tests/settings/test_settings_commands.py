from typer.testing import CliRunner
from vethuq_cli.main import app

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

        result = runner.invoke(app, ["settings", "index", "engine", "show"])

        assert result.exit_code == 0
        assert "quick" in result.stdout

    def test_engine_set_then_show(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "index", "engine", "set", "deep"])
        assert set_result.exit_code == 0

        show_result = runner.invoke(app, ["settings", "index", "engine", "show"])
        assert "deep" in show_result.stdout

    def test_engine_set_rejects_invalid_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "index", "engine", "set", "thorough"])

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
