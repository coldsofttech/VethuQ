"""Small persisted key-value settings store for VethuQ."""

from __future__ import annotations

from vethuq_core.storage import Storage


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
    def get(storage: Storage, key: str) -> str | None:
        return storage.get_setting_value(key)

    @staticmethod
    def set(storage: Storage, key: str, value: str) -> None:
        storage.upsert_setting(key, value)
