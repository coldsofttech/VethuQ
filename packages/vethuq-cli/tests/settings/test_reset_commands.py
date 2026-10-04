import pytest
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.settings import GpuSettings, IndexSettings, OcrSettings, SourceSettings
from vethuq_core.storage import open_storage

runner = CliRunner()

# (arguments that change the setting, arguments that reset it, reads the value, default)
CASES = {
    "gpu": (
        ["settings", "gpu", "enable"],
        ["settings", "gpu", "reset"],
        GpuSettings.is_enabled,
        GpuSettings.DEFAULT_ENABLED,
    ),
    "ocr-retry": (
        ["settings", "ocr", "retry", "set", "9"],
        ["settings", "ocr", "retry", "reset"],
        OcrSettings.get_retry_attempts,
        OcrSettings.DEFAULT_RETRY_ATTEMPTS,
    ),
    "ocr-engine": (
        ["settings", "ocr", "engine", "set", "deep"],
        ["settings", "ocr", "engine", "reset"],
        OcrSettings.get_engine,
        OcrSettings.DEFAULT_ENGINE,
    ),
    "removed-retention": (
        ["settings", "index", "removed-retention", "set", "5"],
        ["settings", "index", "removed-retention", "reset"],
        SourceSettings.get_removed_retention_minutes,
        SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES,
    ),
    "stability-check": (
        ["settings", "index", "stability-check", "set", "0"],
        ["settings", "index", "stability-check", "reset"],
        OcrSettings.get_stability_check_seconds,
        OcrSettings.DEFAULT_STABILITY_CHECK_SECONDS,
    ),
    "thread-workers": (
        ["settings", "index", "thread-workers", "set", "4"],
        ["settings", "index", "thread-workers", "reset"],
        IndexSettings.get_thread_workers,
        IndexSettings.DEFAULT_THREAD_WORKERS,
    ),
    "stale-lock": (
        ["settings", "index", "stale-lock", "set", "disable"],
        ["settings", "index", "stale-lock", "reset"],
        IndexSettings.get_stale_lock,
        IndexSettings.DEFAULT_STALE_LOCK,
    ),
}


def _read(getter):
    storage = open_storage()
    try:
        return getter(storage)
    finally:
        storage.close()


class TestResetCommands:
    @pytest.mark.parametrize("name", CASES)
    def test_reset_restores_the_default(self, use_temp_db, name):
        use_temp_db()
        change, reset, getter, default = CASES[name]
        assert runner.invoke(app, change).exit_code == 0
        assert _read(getter) != default

        result = runner.invoke(app, reset)

        assert result.exit_code == 0
        assert "reset to the default" in result.stdout
        assert _read(getter) == default
