"""Settings for the database."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import InvalidSettingValueError, Settings


class DbSettings:
    INTEGRITY_CHECK_KEY = "db_integrity_check"
    DEFAULT_INTEGRITY_CHECK = "auto"
    INTEGRITY_CHECK_VALUES = ("enable", "disable", "auto")
    INTEGRITY_CHECK_INTERVAL_MINUTES_KEY = "db_integrity_check_interval_minutes"
    DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES = 24 * 60  # 1 day

    @staticmethod
    def get_integrity_check(conn: sqlite3.Connection) -> str:
        """Whether `PRAGMA integrity_check` runs automatically when the database is opened.
        'auto' by default.

        One of 'auto' (run at most once per `integrity_check_interval_minutes` -
        the default), 'enable' (run on every connection), or 'disable' (never
        run automatically - only via `vethuq db integrity-check`).
        """
        value = Settings.get(conn, DbSettings.INTEGRITY_CHECK_KEY)
        return value if value is not None else DbSettings.DEFAULT_INTEGRITY_CHECK

    @staticmethod
    def set_integrity_check(conn: sqlite3.Connection, value: str) -> None:
        if value not in DbSettings.INTEGRITY_CHECK_VALUES:
            raise InvalidSettingValueError(
                f"value must be one of {DbSettings.INTEGRITY_CHECK_VALUES}"
            )
        Settings.set(conn, DbSettings.INTEGRITY_CHECK_KEY, value)

    @staticmethod
    def get_integrity_check_interval_minutes(conn: sqlite3.Connection) -> int:
        """Minutes between automatic integrity checks when `integrity_check` is 'auto'.
        1 day by default.
        """
        value = Settings.get(conn, DbSettings.INTEGRITY_CHECK_INTERVAL_MINUTES_KEY)
        if value is None:
            return DbSettings.DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES
        return int(value)

    @staticmethod
    def set_integrity_check_interval_minutes(conn: sqlite3.Connection, minutes: int) -> None:
        if minutes < 0:
            raise InvalidSettingValueError("minutes must be non-negative")
        Settings.set(conn, DbSettings.INTEGRITY_CHECK_INTERVAL_MINUTES_KEY, str(minutes))
