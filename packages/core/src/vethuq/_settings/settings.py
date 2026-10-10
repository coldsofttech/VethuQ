"""The settings service: named values saved in the database, with defaults."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from vethuq._db import _IntegrityCheck, _Setting
from vethuq._errors import _InvalidSettingValueError
from vethuq._logs import _Log
from vethuq.enums import IntegrityCheckMode, LogLevel, UpdateCheckMode


class _Settings:
    @staticmethod
    def get(session: Session, key: str) -> str | None:
        """The saved value of a setting, or None if it has none (its default applies)."""
        row = session.get(_Setting, key)
        return row.value if row is not None else None

    @staticmethod
    def set(session: Session, key: str, value: str) -> None:
        row = session.get(_Setting, key)
        if row is None:
            session.add(_Setting(key=key, value=value))
        else:
            row.value = value
        session.flush()

    @staticmethod
    def reset(session: Session, key: str) -> None:
        """Forget a setting's saved value so its default applies again."""
        row = session.get(_Setting, key)
        if row is not None:
            session.delete(row)
            session.flush()


class _SourceSettings:
    REMOVED_RETENTION_MINUTES_KEY = "index_removed_source_retention_minutes"
    DEFAULT_REMOVED_RETENTION_MINUTES = 7 * 24 * 60  # 7 days

    @staticmethod
    def get_removed_retention_minutes(session: Session) -> int:
        """Minutes a removed source is kept before it is purged. 7 days unless changed."""
        value = _Settings.get(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY)
        default = _SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default

    @staticmethod
    def set_removed_retention_minutes(session: Session, minutes: int) -> None:
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            raise _InvalidSettingValueError(
                f"The retention must be a whole number of minutes, not {minutes!r}.",
                "Use 0 to purge removed sources at once.",
            )
        if minutes < 0:
            raise _InvalidSettingValueError(
                f"The retention can't be negative ({minutes}).",
                "Use 0 to purge removed sources at once.",
            )
        _Settings.set(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY, str(minutes))

    @staticmethod
    def reset_removed_retention_minutes(session: Session) -> None:
        """Back to the default retention (7 days)."""
        _Settings.reset(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY)


class _LogSettings:
    @staticmethod
    def get_level(session: Session) -> LogLevel:
        """How much the logs record. `info` unless changed."""
        value = _Settings.get(session, _Log.LEVEL_KEY)
        try:
            return LogLevel(value) if value is not None else _Log.DEFAULT_LEVEL
        except ValueError:
            return _Log.DEFAULT_LEVEL

    @staticmethod
    def set_level(session: Session, level: LogLevel | str) -> None:
        try:
            level = LogLevel(level)
        except ValueError:
            options = ", ".join(member.value for member in LogLevel)
            raise _InvalidSettingValueError(
                f"The log level {level!r} isn't one VethuQ has.", f"Use one of: {options}."
            ) from None
        _Settings.set(session, _Log.LEVEL_KEY, level.value)

    @staticmethod
    def reset_level(session: Session) -> None:
        """Back to the default log level (`info`)."""
        _Settings.reset(session, _Log.LEVEL_KEY)

    @staticmethod
    def get_retention_days(session: Session) -> int:
        """How many days of daily log files are kept. 15 unless changed."""
        value = _Settings.get(session, _Log.RETENTION_DAYS_KEY)
        try:
            days = int(value) if value is not None else _Log.DEFAULT_RETENTION_DAYS
        except ValueError:
            return _Log.DEFAULT_RETENTION_DAYS
        return days if days >= 1 else _Log.DEFAULT_RETENTION_DAYS

    @staticmethod
    def set_retention_days(session: Session, days: int) -> None:
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise _InvalidSettingValueError(
                f"The retention must be a whole number of days, at least 1, not {days!r}.",
                "Use 1 to keep only today's log.",
            )
        _Settings.set(session, _Log.RETENTION_DAYS_KEY, str(days))

    @staticmethod
    def reset_retention_days(session: Session) -> None:
        """Back to the default retention (15 days)."""
        _Settings.reset(session, _Log.RETENTION_DAYS_KEY)


@dataclass(frozen=True)
class _UpdateView:
    """What the update check needs from the settings, read in one go."""

    mode: UpdateCheckMode  # in force: off when the environment says so, else the setting
    disabled_by_environment: bool = False
    snoozed: bool = False
    skipped_version: str | None = None


class _UpdateSettings:
    CHECK_KEY = "update_check"
    DEFAULT_CHECK = UpdateCheckMode.ON
    SNOOZE_KEY = "update_snoozed_until"
    DEFAULT_SNOOZE_DAYS = 1
    SKIP_KEY = "update_skipped_version"

    # Set to one of ENV_OFF_VALUES to turn the check off whatever the setting says (CI,
    # locked-down machines). Any other value, or none, leaves the setting in charge.
    ENV_VAR = "VETHUQ_UPDATE_CHECK"
    ENV_OFF_VALUES = ("off", "0", "false", "no", "disable", "disabled")

    @staticmethod
    def disabled_by_environment() -> bool:
        """Whether `VETHUQ_UPDATE_CHECK` switches the check off."""
        value = os.environ.get(_UpdateSettings.ENV_VAR, "").strip().lower()
        return value in _UpdateSettings.ENV_OFF_VALUES

    @staticmethod
    def get_check(session: Session) -> UpdateCheckMode:
        """What the update check does: `on` unless changed."""
        value = _Settings.get(session, _UpdateSettings.CHECK_KEY)
        try:
            return UpdateCheckMode(value) if value is not None else _UpdateSettings.DEFAULT_CHECK
        except ValueError:
            return _UpdateSettings.DEFAULT_CHECK

    @staticmethod
    def set_check(session: Session, mode: UpdateCheckMode | str) -> None:
        try:
            mode = UpdateCheckMode(mode)
        except ValueError:
            options = ", ".join(member.value for member in UpdateCheckMode)
            raise _InvalidSettingValueError(
                f"The update check mode {mode!r} isn't one VethuQ has.", f"Use one of: {options}."
            ) from None
        _Settings.set(session, _UpdateSettings.CHECK_KEY, mode.value)

    @staticmethod
    def reset_check(session: Session) -> None:
        _Settings.reset(session, _UpdateSettings.CHECK_KEY)

    @staticmethod
    def get_snoozed_until(session: Session) -> float | None:
        """When "remind me later" ends (seconds since the epoch), or None when not snoozed."""
        value = _Settings.get(session, _UpdateSettings.SNOOZE_KEY)
        try:
            return float(value) if value else None
        except ValueError:
            return None

    @staticmethod
    def snooze(session: Session, days: float, now: float | None = None) -> None:
        """Hide the update notice for `days` days."""
        if isinstance(days, bool) or not isinstance(days, int | float) or days <= 0:
            raise _InvalidSettingValueError(
                f"The snooze must be a number of days above 0, not {days!r}.",
                "Use clear_snooze() to show the notice again.",
            )
        until = (time.time() if now is None else now) + days * 24 * 60 * 60
        _Settings.set(session, _UpdateSettings.SNOOZE_KEY, repr(until))

    @staticmethod
    def clear_snooze(session: Session) -> None:
        _Settings.reset(session, _UpdateSettings.SNOOZE_KEY)

    @staticmethod
    def is_snoozed(session: Session, now: float | None = None) -> bool:
        until = _UpdateSettings.get_snoozed_until(session)
        return until is not None and (time.time() if now is None else now) < until

    @staticmethod
    def get_skipped_version(session: Session) -> str | None:
        """The version the user chose to skip, or None. A newer version is announced again."""
        return _Settings.get(session, _UpdateSettings.SKIP_KEY) or None

    @staticmethod
    def skip_version(session: Session, version: str) -> None:
        if not isinstance(version, str) or not version.strip():
            raise _InvalidSettingValueError(
                f"The version to skip must be text, not {version!r}.",
                "Use clear_skip() to announce every version again.",
            )
        _Settings.set(session, _UpdateSettings.SKIP_KEY, version.strip())

    @staticmethod
    def clear_skip(session: Session) -> None:
        _Settings.reset(session, _UpdateSettings.SKIP_KEY)

    @staticmethod
    def read(session: Session, now: float | None = None) -> _UpdateView:
        """The mode in force, whether the notice is snoozed, and the version skipped."""
        by_environment = _UpdateSettings.disabled_by_environment()
        mode = UpdateCheckMode.OFF if by_environment else _UpdateSettings.get_check(session)
        return _UpdateView(
            mode=mode,
            disabled_by_environment=by_environment,
            snoozed=_UpdateSettings.is_snoozed(session, now),
            skipped_version=_UpdateSettings.get_skipped_version(session),
        )


class _DatabaseSettings:
    @staticmethod
    def get_integrity_check(session: Session) -> IntegrityCheckMode:
        """When the integrity check runs by itself. `auto` unless changed."""
        value = _Settings.get(session, _IntegrityCheck.MODE_KEY)
        try:
            return IntegrityCheckMode(value) if value is not None else _IntegrityCheck.DEFAULT_MODE
        except ValueError:
            return _IntegrityCheck.DEFAULT_MODE

    @staticmethod
    def set_integrity_check(session: Session, mode: IntegrityCheckMode | str) -> None:
        try:
            mode = IntegrityCheckMode(mode)
        except ValueError:
            options = ", ".join(member.value for member in IntegrityCheckMode)
            raise _InvalidSettingValueError(
                f"The integrity check mode {mode!r} isn't one VethuQ has.",
                f"Use one of: {options}.",
            ) from None
        _Settings.set(session, _IntegrityCheck.MODE_KEY, mode.value)

    @staticmethod
    def reset_integrity_check(session: Session) -> None:
        """Back to the default mode (`auto`)."""
        _Settings.reset(session, _IntegrityCheck.MODE_KEY)

    @staticmethod
    def get_integrity_check_interval_minutes(session: Session) -> int:
        """Minutes between automatic integrity checks in `auto` mode. 1 day unless changed."""
        value = _Settings.get(session, _IntegrityCheck.INTERVAL_KEY)
        default = _IntegrityCheck.DEFAULT_INTERVAL_MINUTES
        try:
            minutes = int(value) if value is not None else default
        except ValueError:
            return default
        return minutes if minutes >= 1 else default

    @staticmethod
    def set_integrity_check_interval_minutes(session: Session, minutes: int) -> None:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
            raise _InvalidSettingValueError(
                f"The interval must be a whole number of minutes, at least 1, not {minutes!r}.",
                "Set the mode to ENABLE to check every time the database is opened.",
            )
        _Settings.set(session, _IntegrityCheck.INTERVAL_KEY, str(minutes))

    @staticmethod
    def reset_integrity_check_interval_minutes(session: Session) -> None:
        """Back to the default interval (1 day)."""
        _Settings.reset(session, _IntegrityCheck.INTERVAL_KEY)
