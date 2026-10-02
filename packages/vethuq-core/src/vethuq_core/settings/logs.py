"""Settings for log files."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import InvalidSettingValueError, Settings


class LogSettings:
    LEVEL_KEY = "log_level"
    DEFAULT_LEVEL = "info"
    LEVEL_VALUES = ("debug", "info", "warning", "error")
    RETENTION_DAYS_KEY = "log_retention_days"
    DEFAULT_RETENTION_DAYS = 15

    @staticmethod
    def get_level(conn: sqlite3.Connection) -> str:
        """Verbosity of VethuQ's log files. 'info' by default.

        One of 'debug', 'info', 'warning' or 'error'.
        """
        value = Settings.get(conn, LogSettings.LEVEL_KEY)
        return value if value is not None else LogSettings.DEFAULT_LEVEL

    @staticmethod
    def set_level(conn: sqlite3.Connection, value: str) -> None:
        if value not in LogSettings.LEVEL_VALUES:
            raise InvalidSettingValueError(f"value must be one of {LogSettings.LEVEL_VALUES}")
        Settings.set(conn, LogSettings.LEVEL_KEY, value)

    @staticmethod
    def get_retention_days(conn: sqlite3.Connection) -> int:
        """How many days of daily log files are kept. 15 by default."""
        value = Settings.get(conn, LogSettings.RETENTION_DAYS_KEY)
        return int(value) if value is not None else LogSettings.DEFAULT_RETENTION_DAYS

    @staticmethod
    def set_retention_days(conn: sqlite3.Connection, days: int) -> None:
        if days < 1:
            raise InvalidSettingValueError("days must be at least 1")
        Settings.set(conn, LogSettings.RETENTION_DAYS_KEY, str(days))
