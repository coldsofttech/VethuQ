"""VethuQ's settings: `VethuQ().settings`."""

from __future__ import annotations

from vethuq._db import _Database
from vethuq._logs import _Log, _Logs
from vethuq._settings import _LogSettings, _SourceSettings
from vethuq.enums import LogLevel

__all__ = ["LogSettings", "Settings", "SourceSettings"]


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


class Settings:
    """VethuQ's settings, grouped by feature.

    Not created directly: use `VethuQ().settings`.
    """

    def __init__(self, database: _Database) -> None:
        self.sources = SourceSettings(database)
        self.logs = LogSettings(database)
