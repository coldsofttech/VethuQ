import pytest
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.settings import (
    DbSettings,
    GpuSettings,
    IndexSettings,
    LogSettings,
    OcrSettings,
    SearchSettings,
    SourceSettings,
)
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
    "db-integrity-check": (
        ["settings", "db", "integrity-check", "set", "disable"],
        ["settings", "db", "integrity-check", "reset"],
        DbSettings.get_integrity_check,
        DbSettings.DEFAULT_INTEGRITY_CHECK,
    ),
    "db-integrity-check-interval": (
        ["settings", "db", "integrity-check", "interval", "set", "5"],
        ["settings", "db", "integrity-check", "interval", "reset"],
        DbSettings.get_integrity_check_interval_minutes,
        DbSettings.DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES,
    ),
    "db-backup": (
        ["settings", "db", "backup", "set", "disable"],
        ["settings", "db", "backup", "reset"],
        DbSettings.get_backup,
        DbSettings.DEFAULT_BACKUP,
    ),
    "db-backup-interval": (
        ["settings", "db", "backup", "interval", "set", "5"],
        ["settings", "db", "backup", "interval", "reset"],
        DbSettings.get_backup_interval_minutes,
        DbSettings.DEFAULT_BACKUP_INTERVAL_MINUTES,
    ),
    "db-backup-retention": (
        ["settings", "db", "backup", "retention", "set", "30"],
        ["settings", "db", "backup", "retention", "reset"],
        DbSettings.get_backup_retention_days,
        DbSettings.DEFAULT_BACKUP_RETENTION_DAYS,
    ),
    "logs-level": (
        ["settings", "logs", "level", "set", "debug"],
        ["settings", "logs", "level", "reset"],
        LogSettings.get_level,
        LogSettings.DEFAULT_LEVEL,
    ),
    "logs-retention": (
        ["settings", "logs", "retention", "set", "30"],
        ["settings", "logs", "retention", "reset"],
        LogSettings.get_retention_days,
        LogSettings.DEFAULT_RETENTION_DAYS,
    ),
    "search-snippet": (
        ["settings", "search", "snippet", "set", "5"],
        ["settings", "search", "snippet", "reset"],
        SearchSettings.get_snippet_context_chars,
        SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS,
    ),
    "search-export-format": (
        ["settings", "search", "export-format", "set", "html"],
        ["settings", "search", "export-format", "reset"],
        SearchSettings.get_export_format,
        SearchSettings.DEFAULT_EXPORT_FORMAT,
    ),
    "search-semantic-threshold": (
        ["settings", "search", "semantic", "threshold", "set", "strict"],
        ["settings", "search", "semantic", "threshold", "reset"],
        SearchSettings.get_semantic_threshold_setting,
        SearchSettings.DEFAULT_SEMANTIC_THRESHOLD,
    ),
    "search-semantic-limit": (
        ["settings", "search", "semantic", "limit", "set", "5"],
        ["settings", "search", "semantic", "limit", "reset"],
        SearchSettings.get_semantic_limit,
        SearchSettings.DEFAULT_SEMANTIC_LIMIT,
    ),
    "search-semantic-combine": (
        ["settings", "search", "semantic", "combine", "set", "lexical"],
        ["settings", "search", "semantic", "combine", "reset"],
        SearchSettings.get_semantic_combine,
        SearchSettings.DEFAULT_SEMANTIC_COMBINE,
    ),
    "search-engine": (
        ["settings", "search", "engine", "set", "exact"],
        ["settings", "search", "engine", "reset"],
        SearchSettings.get_engine,
        SearchSettings.DEFAULT_ENGINE,
    ),
    "search-fuzzy-threshold": (
        ["settings", "search", "fuzzy", "threshold", "set", "strict"],
        ["settings", "search", "fuzzy", "threshold", "reset"],
        SearchSettings.get_fuzzy_threshold_setting,
        SearchSettings.DEFAULT_FUZZY_THRESHOLD,
    ),
    "search-proximity-distance": (
        ["settings", "search", "proximity", "distance", "set", "tight"],
        ["settings", "search", "proximity", "distance", "reset"],
        SearchSettings.get_proximity_distance_setting,
        SearchSettings.DEFAULT_PROXIMITY_DISTANCE,
    ),
    "search-normalize-case": (
        ["settings", "search", "normalize", "case", "set", "match"],
        ["settings", "search", "normalize", "case", "reset"],
        SearchSettings.get_case,
        SearchSettings.NORMALIZE_AUTO,
    ),
    "search-normalize-unicode": (
        ["settings", "search", "normalize", "unicode", "set", "full"],
        ["settings", "search", "normalize", "unicode", "reset"],
        SearchSettings.get_unicode,
        SearchSettings.NORMALIZE_AUTO,
    ),
    "search-normalize-leetspeak": (
        ["settings", "search", "normalize", "leetspeak", "set", "extended"],
        ["settings", "search", "normalize", "leetspeak", "reset"],
        SearchSettings.get_leetspeak,
        SearchSettings.NORMALIZE_AUTO,
    ),
    "search-noise": (
        ["settings", "search", "noise-fuzzy", "noise", "set", "high"],
        ["settings", "search", "noise-fuzzy", "noise", "reset"],
        SearchSettings.get_noise_level,
        SearchSettings.DEFAULT_NOISE,
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
