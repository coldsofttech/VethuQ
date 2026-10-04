"""The database settings as editable fields: integrity check and automatic backup."""

from __future__ import annotations

from vethuq_core.settings import DbSettings
from vethuq_core.storage import Storage

from vethuq_ui.windows.settings.fields import ChoiceField, DurationField, NumberField


class DbFields:
    BACKUP_RETENTION_MAX_DAYS = 365

    @staticmethod
    def integrity_check(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Integrity check",
            "Look for database corruption when it is opened. Auto checks at most once per "
            "interval, Enable every time, and Disable only when you run it yourself.",
            "Integrity check",
            DbSettings.DEFAULT_INTEGRITY_CHECK,
            DbSettings.get_integrity_check,
            DbSettings.set_integrity_check,
            DbSettings.reset_integrity_check,
            choices=[(value, value.capitalize()) for value in DbSettings.INTEGRITY_CHECK_VALUES],
        )

    @staticmethod
    def integrity_check_interval(storage: Storage) -> DurationField:
        return DurationField(
            storage,
            "Integrity check interval",
            "How long to wait between automatic checks when the check is Auto. "
            "0 checks every time.",
            "Integrity check interval",
            str(DbSettings.DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES),
            DbSettings.get_integrity_check_interval_minutes,
            lambda s, v: DbSettings.set_integrity_check_interval_minutes(s, int(v)),
            DbSettings.reset_integrity_check_interval_minutes,
        )

    @staticmethod
    def backup(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Automatic backup",
            "Take a compressed backup when the database is opened.",
            "Automatic backup",
            DbSettings.DEFAULT_BACKUP,
            DbSettings.get_backup,
            DbSettings.set_backup,
            DbSettings.reset_backup,
            choices=[(value, value.capitalize()) for value in DbSettings.BACKUP_VALUES],
        )

    @staticmethod
    def backup_interval(storage: Storage) -> DurationField:
        return DurationField(
            storage,
            "Backup interval",
            "At most one automatic backup per interval.",
            "Backup interval",
            str(DbSettings.DEFAULT_BACKUP_INTERVAL_MINUTES),
            DbSettings.get_backup_interval_minutes,
            lambda s, v: DbSettings.set_backup_interval_minutes(s, int(v)),
            DbSettings.reset_backup_interval_minutes,
        )

    @staticmethod
    def backup_retention(storage: Storage) -> NumberField:
        return NumberField(
            storage,
            "Backup retention",
            "Days automatic backups are kept before they are deleted.",
            "Backup retention",
            str(DbSettings.DEFAULT_BACKUP_RETENTION_DAYS),
            DbSettings.get_backup_retention_days,
            lambda s, v: DbSettings.set_backup_retention_days(s, int(v)),
            DbSettings.reset_backup_retention_days,
            minimum=1,
            maximum=DbFields.BACKUP_RETENTION_MAX_DAYS,
            step=1,
            unit="days",
        )
