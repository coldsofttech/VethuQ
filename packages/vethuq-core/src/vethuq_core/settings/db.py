"""Settings for the database."""

from __future__ import annotations

from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class DbSettings:
    INTEGRITY_CHECK_KEY = "db_integrity_check"
    DEFAULT_INTEGRITY_CHECK = "auto"
    INTEGRITY_CHECK_VALUES = ("enable", "disable", "auto")
    INTEGRITY_CHECK_INTERVAL_MINUTES_KEY = "db_integrity_check_interval_minutes"
    DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES = 24 * 60  # 1 day

    BACKUP_KEY = "db_backup"
    DEFAULT_BACKUP = "enable"
    BACKUP_VALUES = ("enable", "disable")
    BACKUP_INTERVAL_MINUTES_KEY = "db_backup_interval_minutes"
    DEFAULT_BACKUP_INTERVAL_MINUTES = 24 * 60  # 1 day
    BACKUP_RETENTION_DAYS_KEY = "db_backup_retention_days"
    DEFAULT_BACKUP_RETENTION_DAYS = 7

    @staticmethod
    def get_backup(storage: Storage) -> str:
        """Whether a compressed backup is taken automatically when the database is opened.
        'enable' by default; at most one per `backup_interval_minutes`.
        """
        value = Settings.get(storage, DbSettings.BACKUP_KEY)
        return value if value is not None else DbSettings.DEFAULT_BACKUP

    @staticmethod
    def set_backup(storage: Storage, value: str) -> None:
        if value not in DbSettings.BACKUP_VALUES:
            raise InvalidSettingValueError(f"value must be one of {DbSettings.BACKUP_VALUES}")
        Settings.set(storage, DbSettings.BACKUP_KEY, value)

    @staticmethod
    def get_backup_interval_minutes(storage: Storage) -> int:
        """Minutes between automatic backups. 1 day by default."""
        value = Settings.get(storage, DbSettings.BACKUP_INTERVAL_MINUTES_KEY)
        if value is None:
            return DbSettings.DEFAULT_BACKUP_INTERVAL_MINUTES
        return int(value)

    @staticmethod
    def set_backup_interval_minutes(storage: Storage, minutes: int) -> None:
        if minutes < 1:
            raise InvalidSettingValueError("minutes must be at least 1")
        Settings.set(storage, DbSettings.BACKUP_INTERVAL_MINUTES_KEY, str(minutes))

    @staticmethod
    def get_backup_retention_days(storage: Storage) -> int:
        """Days automatic backups are kept before being pruned. 7 by default."""
        value = Settings.get(storage, DbSettings.BACKUP_RETENTION_DAYS_KEY)
        if value is None:
            return DbSettings.DEFAULT_BACKUP_RETENTION_DAYS
        return int(value)

    @staticmethod
    def set_backup_retention_days(storage: Storage, days: int) -> None:
        if days < 1:
            raise InvalidSettingValueError("days must be at least 1")
        Settings.set(storage, DbSettings.BACKUP_RETENTION_DAYS_KEY, str(days))

    @staticmethod
    def get_integrity_check(storage: Storage) -> str:
        """Whether `PRAGMA integrity_check` runs automatically when the database is opened.
        'auto' by default.

        One of 'auto' (run at most once per `integrity_check_interval_minutes` -
        the default), 'enable' (run on every connection), or 'disable' (never
        run automatically - only via `vethuq db integrity-check`).
        """
        value = Settings.get(storage, DbSettings.INTEGRITY_CHECK_KEY)
        return value if value is not None else DbSettings.DEFAULT_INTEGRITY_CHECK

    @staticmethod
    def set_integrity_check(storage: Storage, value: str) -> None:
        if value not in DbSettings.INTEGRITY_CHECK_VALUES:
            raise InvalidSettingValueError(
                f"value must be one of {DbSettings.INTEGRITY_CHECK_VALUES}"
            )
        Settings.set(storage, DbSettings.INTEGRITY_CHECK_KEY, value)

    @staticmethod
    def get_integrity_check_interval_minutes(storage: Storage) -> int:
        """Minutes between automatic integrity checks when `integrity_check` is 'auto'.
        1 day by default.
        """
        value = Settings.get(storage, DbSettings.INTEGRITY_CHECK_INTERVAL_MINUTES_KEY)
        if value is None:
            return DbSettings.DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES
        return int(value)

    @staticmethod
    def set_integrity_check_interval_minutes(storage: Storage, minutes: int) -> None:
        if minutes < 0:
            raise InvalidSettingValueError("minutes must be non-negative")
        Settings.set(storage, DbSettings.INTEGRITY_CHECK_INTERVAL_MINUTES_KEY, str(minutes))
