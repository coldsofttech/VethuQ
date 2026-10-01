"""Settings for registered sources."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import InvalidSettingValueError, Settings


class SourceSettings:
    REMOVED_RETENTION_MINUTES_KEY = "index_removed_source_retention_minutes"
    DEFAULT_REMOVED_RETENTION_MINUTES = 7 * 24 * 60  # 7 days

    @staticmethod
    def get_removed_retention_minutes(conn: sqlite3.Connection) -> int:
        """Minutes a removed source is kept before it's purged from the DB. 7 days by default."""
        value = Settings.get(conn, SourceSettings.REMOVED_RETENTION_MINUTES_KEY)
        return int(value) if value is not None else SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES

    @staticmethod
    def set_removed_retention_minutes(conn: sqlite3.Connection, minutes: int) -> None:
        if minutes < 0:
            raise InvalidSettingValueError("minutes must be non-negative")
        Settings.set(conn, SourceSettings.REMOVED_RETENTION_MINUTES_KEY, str(minutes))
