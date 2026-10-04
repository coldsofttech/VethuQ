"""Settings for log files."""

from __future__ import annotations

from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class LogSettings:
    LEVEL_KEY = "log_level"
    DEFAULT_LEVEL = "info"
    LEVEL_VALUES = ("debug", "info", "warning", "error")
    RETENTION_DAYS_KEY = "log_retention_days"
    DEFAULT_RETENTION_DAYS = 15

    @staticmethod
    def get_level(storage: Storage) -> str:
        """Verbosity of VethuQ's log files. 'info' by default.

        One of 'debug', 'info', 'warning' or 'error'.
        """
        value = Settings.get(storage, LogSettings.LEVEL_KEY)
        return value if value is not None else LogSettings.DEFAULT_LEVEL

    @staticmethod
    def set_level(storage: Storage, value: str) -> None:
        if value not in LogSettings.LEVEL_VALUES:
            raise InvalidSettingValueError(f"value must be one of {LogSettings.LEVEL_VALUES}")
        Settings.set(storage, LogSettings.LEVEL_KEY, value)

    @staticmethod
    def reset_level(storage: Storage) -> None:
        """Back to the default log level."""
        LogSettings.set_level(storage, LogSettings.DEFAULT_LEVEL)

    @staticmethod
    def get_retention_days(storage: Storage) -> int:
        """How many days of daily log files are kept. 15 by default."""
        value = Settings.get(storage, LogSettings.RETENTION_DAYS_KEY)
        return int(value) if value is not None else LogSettings.DEFAULT_RETENTION_DAYS

    @staticmethod
    def set_retention_days(storage: Storage, days: int) -> None:
        if days < 1:
            raise InvalidSettingValueError("days must be at least 1")
        Settings.set(storage, LogSettings.RETENTION_DAYS_KEY, str(days))

    @staticmethod
    def reset_retention_days(storage: Storage) -> None:
        """Back to the default number of days of log files kept."""
        LogSettings.set_retention_days(storage, LogSettings.DEFAULT_RETENTION_DAYS)
