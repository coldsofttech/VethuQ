import pytest
from vethuq_core.settings import DbSettings
from vethuq_core.storage import Storage

# (changes the setting, resets it, reads it back, the default)
CASES = {
    "integrity-check": (
        lambda s: DbSettings.set_integrity_check(s, "disable"),
        DbSettings.reset_integrity_check,
        DbSettings.get_integrity_check,
        DbSettings.DEFAULT_INTEGRITY_CHECK,
    ),
    "integrity-check-interval": (
        lambda s: DbSettings.set_integrity_check_interval_minutes(s, 5),
        DbSettings.reset_integrity_check_interval_minutes,
        DbSettings.get_integrity_check_interval_minutes,
        DbSettings.DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES,
    ),
    "backup": (
        lambda s: DbSettings.set_backup(s, "disable"),
        DbSettings.reset_backup,
        DbSettings.get_backup,
        DbSettings.DEFAULT_BACKUP,
    ),
    "backup-interval": (
        lambda s: DbSettings.set_backup_interval_minutes(s, 5),
        DbSettings.reset_backup_interval_minutes,
        DbSettings.get_backup_interval_minutes,
        DbSettings.DEFAULT_BACKUP_INTERVAL_MINUTES,
    ),
    "backup-retention": (
        lambda s: DbSettings.set_backup_retention_days(s, 30),
        DbSettings.reset_backup_retention_days,
        DbSettings.get_backup_retention_days,
        DbSettings.DEFAULT_BACKUP_RETENTION_DAYS,
    ),
}


class TestDbSettingsReset:
    @pytest.mark.parametrize("name", CASES)
    def test_reset_restores_the_default(self, storage: Storage, name):
        change, reset, read, default = CASES[name]
        change(storage)
        assert read(storage) != default

        reset(storage)

        assert read(storage) == default
