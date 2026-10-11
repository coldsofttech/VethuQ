"""VethuQ's settings: `VethuQ().settings`."""

from __future__ import annotations

from datetime import UTC, datetime

from vethuq._db import _Database, _IntegrityCheck
from vethuq._languages import _LanguageCatalog, _Languages
from vethuq._logs import _Log, _Logs
from vethuq._settings import (
    _ConfidenceSettings,
    _DatabaseSettings,
    _IndexSettings,
    _LanguageSettings,
    _LogSettings,
    _MetricsSettings,
    _SourceSettings,
    _UpdateSettings,
)
from vethuq.enums import IntegrityCheckMode, LogLevel, UpdateCheckMode

__all__ = [
    "ConfidenceSettings",
    "MetricsSettings",
    "DatabaseSettings",
    "IndexSettings",
    "LanguageSettings",
    "LogSettings",
    "Settings",
    "SourceSettings",
    "UpdateSettings",
]


class SourceSettings:
    """Settings for sources.

    Not created directly: use `VethuQ().settings.sources`.
    """

    DEFAULT_REMOVED_RETENTION_MINUTES = _SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_removed_retention_minutes(self) -> int:
        """Minutes a removed source is kept before it is purged. 7 days unless changed."""
        with self._database.session() as session:
            return _SourceSettings.get_removed_retention_minutes(session)

    def set_removed_retention_minutes(self, minutes: int) -> None:
        """Keep removed sources for `minutes` before they are purged; 0 purges them at once.

        Raises `InvalidSettingValueError` if `minutes` isn't a whole number of 0 or more.
        """
        with self._database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, minutes)

    def reset_removed_retention_minutes(self) -> None:
        """Back to the default retention (7 days)."""
        with self._database.session() as session:
            _SourceSettings.reset_removed_retention_minutes(session)


class IndexSettings:
    """Settings for indexing.

    Not created directly: use `VethuQ().settings.index`.
    """

    MAX_WORKERS = _IndexSettings.MAX_WORKERS
    DEFAULT_RETRY_ATTEMPTS = _IndexSettings.DEFAULT_RETRY_ATTEMPTS
    DEFAULT_STABILITY_CHECK_SECONDS = _IndexSettings.DEFAULT_STABILITY_CHECK_SECONDS

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_workers(self) -> int | str:
        """How many files are indexed at once: `"auto"` (sized to the machine) unless changed."""
        with self._database.session() as session:
            return _IndexSettings.get_workers(session)

    def set_workers(self, workers: int | str) -> None:
        """Index `workers` files at once: `"auto"`, or 0 to 8 (0 uses the calling thread alone).

        Raises `InvalidSettingValueError` for anything else.
        """
        with self._database.session() as session:
            _IndexSettings.set_workers(session, workers)

    def reset_workers(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_workers(session)

    def get_retry_attempts(self) -> int:
        """How many times a failed file is tried again within a run. 3 unless changed."""
        with self._database.session() as session:
            return _IndexSettings.get_retry_attempts(session)

    def set_retry_attempts(self, attempts: int) -> None:
        """Try a failed file again up to `attempts` times; 0 tries each file once.

        Raises `InvalidSettingValueError` unless it is a whole number of 0 or more.
        """
        with self._database.session() as session:
            _IndexSettings.set_retry_attempts(session, attempts)

    def reset_retry_attempts(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_retry_attempts(session)

    def get_stability_check_seconds(self) -> float:
        """How long a run waits to be sure files have stopped changing. 1 second unless changed."""
        with self._database.session() as session:
            return _IndexSettings.get_stability_check_seconds(session)

    def set_stability_check_seconds(self, seconds: float) -> None:
        """Wait `seconds` before indexing files that may still be being written; 0 turns it off.

        Raises `InvalidSettingValueError` unless it is 0 or more.
        """
        with self._database.session() as session:
            _IndexSettings.set_stability_check_seconds(session, seconds)

    def reset_stability_check_seconds(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_stability_check_seconds(session)


class LanguageSettings:
    """Settings for languages.

    Not created directly: use `VethuQ().settings.languages`.
    """

    def __init__(self, database: _Database, catalog: _LanguageCatalog) -> None:
        self._database = database
        self._catalog = catalog

    def get_languages(self) -> list[str]:
        """The language ids a source with none of its own is read in. The system default
        (English) unless changed; a saved language that is no longer usable is left out."""
        with self._database.session() as session:
            return _Languages.default_ids(session, self._catalog.specs())

    def set_languages(self, languages: list[str]) -> list[str]:
        """Read sources with no languages of their own in `languages`, and return them.

        Raises `InvalidSettingValueError` for an empty list and `LanguageUnavailableError` for a
        language that is unknown, unavailable or disabled.
        """
        with self._database.session() as session:
            return _Languages.set_default_ids(session, self._catalog.specs(), languages)

    def reset_languages(self) -> None:
        """Back to the system default (English)."""
        with self._database.session() as session:
            _LanguageSettings.set_default(session, [])


class LogSettings:
    """Settings for the logs.

    Not created directly: use `VethuQ().settings.logs`. A change takes effect at once for
    logs already being written.
    """

    DEFAULT_LEVEL = _Log.DEFAULT_LEVEL
    DEFAULT_RETENTION_DAYS = _Log.DEFAULT_RETENTION_DAYS

    def __init__(self, database: _Database) -> None:
        self._database = database

    def _apply(self) -> None:
        _Logs.reconfigure(self._database.db_path)

    def get_level(self) -> LogLevel:
        """How much the logs record: a `LogLevel`. `INFO` unless changed."""
        with self._database.session() as session:
            return _LogSettings.get_level(session)

    def set_level(self, level: LogLevel | str) -> None:
        """Record entries at or above this level. Raises `InvalidSettingValueError` for a
        value that isn't a `LogLevel`."""
        with self._database.session() as session:
            _LogSettings.set_level(session, level)
        self._apply()

    def reset_level(self) -> None:
        """Back to the default level (`INFO`)."""
        with self._database.session() as session:
            _LogSettings.reset_level(session)
        self._apply()

    def get_retention_days(self) -> int:
        """How many days of daily log files are kept. 15 unless changed."""
        with self._database.session() as session:
            return _LogSettings.get_retention_days(session)

    def set_retention_days(self, days: int) -> None:
        """Keep `days` days of log files. Raises `InvalidSettingValueError` unless `days` is
        a whole number of at least 1."""
        with self._database.session() as session:
            _LogSettings.set_retention_days(session, days)
        self._apply()

    def reset_retention_days(self) -> None:
        """Back to the default retention (15 days)."""
        with self._database.session() as session:
            _LogSettings.reset_retention_days(session)
        self._apply()


class UpdateSettings:
    """Settings for the update check: whether it runs, and what the user chose to ignore.

    Not created directly: use `VethuQ().settings.updates`.
    """

    ENV_VAR = _UpdateSettings.ENV_VAR
    DEFAULT_CHECK = _UpdateSettings.DEFAULT_CHECK
    DEFAULT_SNOOZE_DAYS = _UpdateSettings.DEFAULT_SNOOZE_DAYS

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_check(self) -> UpdateCheckMode:
        """What the update check does, as an `UpdateCheckMode`: `ON` (the default) checks and
        offers to update, `NOTIFY_ONLY` checks and only tells you, `OFF` never checks.

        This is the saved setting; `disabled_by_environment()` says whether `VETHUQ_UPDATE_CHECK`
        overrides it.
        """
        with self._database.session() as session:
            return _UpdateSettings.get_check(session)

    def set_check(self, mode: UpdateCheckMode | str) -> None:
        """Set what the update check does. Raises `InvalidSettingValueError` for a value that
        isn't an `UpdateCheckMode`."""
        with self._database.session() as session:
            _UpdateSettings.set_check(session, mode)

    def reset_check(self) -> None:
        """Back to the default (`ON`)."""
        with self._database.session() as session:
            _UpdateSettings.reset_check(session)

    @staticmethod
    def disabled_by_environment() -> bool:
        """Whether the environment variable `VETHUQ_UPDATE_CHECK` (`off`, `0`, `false`, `no`,
        `disable` or `disabled`) switches the check off whatever the setting says."""
        return _UpdateSettings.disabled_by_environment()

    def get_snoozed_until(self) -> datetime | None:
        """When "remind me later" ends (UTC), or None when the notice isn't snoozed."""
        with self._database.session() as session:
            until = _UpdateSettings.get_snoozed_until(session)
        return datetime.fromtimestamp(until, UTC) if until is not None else None

    def snooze(self, days: float = DEFAULT_SNOOZE_DAYS) -> None:
        """Hide the update notice for `days` days (1 by default). Raises
        `InvalidSettingValueError` unless `days` is a number above 0."""
        with self._database.session() as session:
            _UpdateSettings.snooze(session, days)

    def clear_snooze(self) -> None:
        """Show the update notice again."""
        with self._database.session() as session:
            _UpdateSettings.clear_snooze(session)

    def get_skipped_version(self) -> str | None:
        """The version the user chose to skip, or None. A newer version is announced again."""
        with self._database.session() as session:
            return _UpdateSettings.get_skipped_version(session)

    def skip_version(self, version: str) -> None:
        """Stop announcing this version (only this one). Raises `InvalidSettingValueError` for
        an empty version."""
        with self._database.session() as session:
            _UpdateSettings.skip_version(session, version)

    def clear_skip(self) -> None:
        """Announce every version again."""
        with self._database.session() as session:
            _UpdateSettings.clear_skip(session)


class DatabaseSettings:
    """Settings for the database.

    Not created directly: use `VethuQ().settings.database`. They are read when the database is
    opened, so a change applies the next time a client opens it.
    """

    DEFAULT_INTEGRITY_CHECK = _IntegrityCheck.DEFAULT_MODE
    DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES = _IntegrityCheck.DEFAULT_INTERVAL_MINUTES

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_integrity_check(self) -> IntegrityCheckMode:
        """When the integrity check runs by itself, as an `IntegrityCheckMode`: `AUTO` (the
        default) when the database is opened, at most once per interval; `ENABLE` every time it is
        opened; `DISABLE` never (`client.db.integrity_check()` still works)."""
        with self._database.session() as session:
            return _DatabaseSettings.get_integrity_check(session)

    def set_integrity_check(self, mode: IntegrityCheckMode | str) -> None:
        """Set when the integrity check runs by itself. Raises `InvalidSettingValueError` for a
        value that isn't an `IntegrityCheckMode`."""
        with self._database.session() as session:
            _DatabaseSettings.set_integrity_check(session, mode)

    def reset_integrity_check(self) -> None:
        """Back to the default (`AUTO`)."""
        with self._database.session() as session:
            _DatabaseSettings.reset_integrity_check(session)

    def get_integrity_check_interval_minutes(self) -> int:
        """Minutes between automatic checks in `AUTO` mode. 1 day unless changed."""
        with self._database.session() as session:
            return _DatabaseSettings.get_integrity_check_interval_minutes(session)

    def set_integrity_check_interval_minutes(self, minutes: int) -> None:
        """Check at most once per `minutes` in `AUTO` mode. Raises `InvalidSettingValueError`
        unless `minutes` is a whole number of at least 1."""
        with self._database.session() as session:
            _DatabaseSettings.set_integrity_check_interval_minutes(session, minutes)

    def reset_integrity_check_interval_minutes(self) -> None:
        """Back to the default interval (1 day)."""
        with self._database.session() as session:
            _DatabaseSettings.reset_integrity_check_interval_minutes(session)


class MetricsSettings:
    """Settings for sharing anonymous usage metrics.

    Not created directly: use `VethuQ().settings.metrics`. `VethuQ().metrics` is the usual way to
    turn sharing on or off.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_opt_in(self) -> bool:
        """Whether metrics are shared. Off unless you turned it on."""
        with self._database.session() as session:
            return _MetricsSettings.get_opt_in(session)

    def set_opt_in(self, on: bool) -> None:
        """Turn sharing on or off. Raises `InvalidSettingValueError` unless `on` is a bool."""
        with self._database.session() as session:
            _MetricsSettings.set_opt_in(session, on)

    def reset_opt_in(self) -> None:
        with self._database.session() as session:
            _MetricsSettings.reset_opt_in(session)


class ConfidenceSettings:
    """Where the confidence bands start.

    Not created directly: use `VethuQ().settings.confidence`. A page is `high`, `medium`, `low` or
    `unreliable` by its confidence in percent; by default 90, 80 and 70.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_bands(self) -> tuple[int, int, int]:
        """The percentages the `low`, `medium` and `high` bands start at. (70, 80, 90) unless
        changed; below the first is `unreliable`."""
        with self._database.session() as session:
            return _ConfidenceSettings.get_bands(session)

    def set_bands(self, low: int, medium: int, high: int) -> None:
        """Change the bands: whole percentages, rising, from 0 to 100. Raises
        `InvalidSettingValueError` for anything else."""
        with self._database.session() as session:
            _ConfidenceSettings.set_bands(session, low, medium, high)

    def reset_bands(self) -> None:
        with self._database.session() as session:
            _ConfidenceSettings.reset_bands(session)


class Settings:
    """VethuQ's settings, grouped by feature.

    Not created directly: use `VethuQ().settings`.
    """

    def __init__(self, database: _Database, catalog: _LanguageCatalog) -> None:
        self.sources = SourceSettings(database)
        self.languages = LanguageSettings(database, catalog)
        self.index = IndexSettings(database)
        self.metrics = MetricsSettings(database)
        self.confidence = ConfidenceSettings(database)
        self.logs = LogSettings(database)
        self.updates = UpdateSettings(database)
        self.database = DatabaseSettings(database)
