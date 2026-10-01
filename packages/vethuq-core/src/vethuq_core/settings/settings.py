"""Small persisted key-value settings store for VethuQ."""

from __future__ import annotations

import sqlite3

from vethuq_core.db.queries import Settings as SettingsQuery


class SettingsError(Exception):
    """Base class for settings errors."""


class InvalidSettingValueError(SettingsError, ValueError):
    """A setting value failed validation.

    Also a `ValueError` for backward compatibility with existing callers
    (e.g. the CLI) that already catch `ValueError` around the `set_*`
    methods of the settings classes.
    """


class Settings:
    @staticmethod
    def get(conn: sqlite3.Connection, key: str) -> str | None:
        return SettingsQuery.get_value(conn, key)

    @staticmethod
    def set(conn: sqlite3.Connection, key: str, value: str) -> None:
        SettingsQuery.upsert(conn, key, value)
