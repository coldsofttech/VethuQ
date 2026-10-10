"""Settings for the update check: whether it runs, and what the user chose to ignore."""

from __future__ import annotations

import os
import time

from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class UpdateSettings:
    CHECK_KEY = "update_check"
    DEFAULT_CHECK = "on"
    CHECK_VALUES = ("on", "notify-only", "off")

    # Set to one of OFF_VALUES to turn the check off whatever the setting says (CI, locked-down
    # machines). Any other value, or none, leaves the setting in charge.
    ENV_VAR = "VETHUQ_UPDATE_CHECK"
    ENV_OFF_VALUES = ("off", "0", "false", "no", "disable", "disabled")

    SNOOZE_KEY = "update_snoozed_until"
    DEFAULT_SNOOZE_DAYS = 1
    SKIP_KEY = "update_skipped_version"

    @staticmethod
    def get_check(storage: Storage) -> str:
        """What the update check does: 'on' (the default) checks and offers to update,
        'notify-only' checks and only tells you, 'off' never checks.
        """
        value = Settings.get(storage, UpdateSettings.CHECK_KEY)
        return value if value in UpdateSettings.CHECK_VALUES else UpdateSettings.DEFAULT_CHECK

    @staticmethod
    def set_check(storage: Storage, value: str) -> None:
        if value not in UpdateSettings.CHECK_VALUES:
            raise InvalidSettingValueError(f"value must be one of {UpdateSettings.CHECK_VALUES}")
        Settings.set(storage, UpdateSettings.CHECK_KEY, value)

    @staticmethod
    def reset_check(storage: Storage) -> None:
        """Back to the default: 'on'."""
        UpdateSettings.set_check(storage, UpdateSettings.DEFAULT_CHECK)

    @staticmethod
    def disabled_by_environment() -> bool:
        """Whether `VETHUQ_UPDATE_CHECK` switches the check off."""
        return os.environ.get(UpdateSettings.ENV_VAR, "").strip().lower() in (
            UpdateSettings.ENV_OFF_VALUES
        )

    @staticmethod
    def effective_check(storage: Storage) -> str:
        """The mode in force: 'off' when the environment variable says so, else the setting."""
        if UpdateSettings.disabled_by_environment():
            return "off"
        return UpdateSettings.get_check(storage)

    @staticmethod
    def get_snoozed_until(storage: Storage) -> float | None:
        """When "remind me later" ends (seconds since the epoch), or None when not snoozed."""
        value = Settings.get(storage, UpdateSettings.SNOOZE_KEY)
        try:
            return float(value) if value else None
        except ValueError:
            return None

    @staticmethod
    def snooze(
        storage: Storage, days: float = DEFAULT_SNOOZE_DAYS, now: float | None = None
    ) -> None:
        """Hide the update notice for `days` days."""
        if days <= 0:
            raise InvalidSettingValueError("days must be greater than 0")
        until = (time.time() if now is None else now) + days * 24 * 60 * 60
        Settings.set(storage, UpdateSettings.SNOOZE_KEY, repr(until))

    @staticmethod
    def clear_snooze(storage: Storage) -> None:
        Settings.set(storage, UpdateSettings.SNOOZE_KEY, "")

    @staticmethod
    def is_snoozed(storage: Storage, now: float | None = None) -> bool:
        until = UpdateSettings.get_snoozed_until(storage)
        return until is not None and (time.time() if now is None else now) < until

    @staticmethod
    def get_skipped_version(storage: Storage) -> str | None:
        """The version the user chose to skip, or None. A newer version is announced again."""
        return Settings.get(storage, UpdateSettings.SKIP_KEY) or None

    @staticmethod
    def skip_version(storage: Storage, version: str) -> None:
        if not version.strip():
            raise InvalidSettingValueError("version must not be empty")
        Settings.set(storage, UpdateSettings.SKIP_KEY, version.strip())

    @staticmethod
    def clear_skip(storage: Storage) -> None:
        Settings.set(storage, UpdateSettings.SKIP_KEY, "")
