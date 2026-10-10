"""VethuQ's settings: `VethuQ().settings`."""

from __future__ import annotations

from datetime import UTC, datetime

from vethuq._db import _Database
from vethuq._logs import _Log, _Logs
from vethuq._settings import _LogSettings, _SourceSettings, _UpdateSettings
from vethuq.enums import LogLevel, UpdateCheckMode

__all__ = ["LogSettings", "Settings", "SourceSettings", "UpdateSettings"]


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


class Settings:
    """VethuQ's settings, grouped by feature.

    Not created directly: use `VethuQ().settings`.
    """

    def __init__(self, database: _Database) -> None:
        self.sources = SourceSettings(database)
        self.logs = LogSettings(database)
        self.updates = UpdateSettings(database)
