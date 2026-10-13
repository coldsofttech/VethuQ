"""The settings service: named values saved in the database, with defaults."""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
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


class _OcrSettings:
    ENGINE_KEY = "ocr_engine"
    # How far a run reads: each phase also does the ones before it. The phases come from add-ons.
    ENGINES = ("quick", "moderate", "deep")
    DEFAULT_ENGINE = "quick"
    GPU_KEY = "gpu_enabled"

    @staticmethod
    def get_gpu(session: Session) -> bool:
        """Whether OCR engines are asked to use the GPU. Off unless changed."""
        return (_Settings.get(session, _OcrSettings.GPU_KEY) or "false").lower() == "true"

    @staticmethod
    def set_gpu(session: Session, enabled: object) -> bool:
        if not isinstance(enabled, bool):
            raise _InvalidSettingValueError(f"gpu must be True or False, not {enabled!r}.")
        _Settings.set(session, _OcrSettings.GPU_KEY, "true" if enabled else "false")
        return enabled

    @staticmethod
    def reset_gpu(session: Session) -> None:
        _Settings.reset(session, _OcrSettings.GPU_KEY)

    @staticmethod
    def parse_engine(value: object) -> str:
        engine = value.strip().lower() if isinstance(value, str) else ""
        if engine not in _OcrSettings.ENGINES:
            raise _InvalidSettingValueError(
                f"The OCR engine must be one of {', '.join(_OcrSettings.ENGINES)}, not {value!r}.",
                "quick reads upright text only; moderate and deep also read rotated text.",
            )
        return engine

    @staticmethod
    def get_engine(session: Session) -> str:
        """The deepest OCR phase a run goes to. `quick` unless changed."""
        value = _Settings.get(session, _OcrSettings.ENGINE_KEY)
        try:
            return _OcrSettings.parse_engine(value) if value else _OcrSettings.DEFAULT_ENGINE
        except _InvalidSettingValueError:
            return _OcrSettings.DEFAULT_ENGINE

    @staticmethod
    def set_engine(session: Session, value: object) -> str:
        engine = _OcrSettings.parse_engine(value)
        _Settings.set(session, _OcrSettings.ENGINE_KEY, engine)
        return engine

    @staticmethod
    def reset_engine(session: Session) -> None:
        _Settings.reset(session, _OcrSettings.ENGINE_KEY)


class _IndexSettings:
    WORKERS_KEY = "index_workers"
    RETRY_ATTEMPTS_KEY = "index_retry_attempts"
    STABILITY_CHECK_KEY = "index_stability_check_seconds"
    AUTO = "auto"
    MAX_WORKERS = 8
    DEFAULT_RETRY_ATTEMPTS = 3
    DEFAULT_STABILITY_CHECK_SECONDS = 1.0
    STALE_LOCK_KEY = "index_stale_lock"
    STALE_LOCK_VALUES = ("auto", "enable", "disable")
    DEFAULT_STALE_LOCK = "auto"

    @staticmethod
    def get_stale_lock(session: Session) -> str:
        """What happens to a run left behind by a process that ended. `auto` unless changed."""
        value = _Settings.get(session, _IndexSettings.STALE_LOCK_KEY)
        return (
            value
            if value in _IndexSettings.STALE_LOCK_VALUES
            else _IndexSettings.DEFAULT_STALE_LOCK
        )

    @staticmethod
    def set_stale_lock(session: Session, value: object) -> str:
        if value not in _IndexSettings.STALE_LOCK_VALUES:
            raise _InvalidSettingValueError(
                "The stale-lock mode must be one of "
                f"{', '.join(_IndexSettings.STALE_LOCK_VALUES)}, not {value!r}."
            )
        _Settings.set(session, _IndexSettings.STALE_LOCK_KEY, value)  # type: ignore[arg-type]
        return value  # type: ignore[return-value]

    @staticmethod
    def reset_stale_lock(session: Session) -> None:
        _Settings.reset(session, _IndexSettings.STALE_LOCK_KEY)

    @staticmethod
    def parse_workers(value: object) -> int | str:
        """`"auto"`, or a whole number from 0 to 8 (0 works on the calling thread alone)."""
        if isinstance(value, str) and value.strip().lower() == _IndexSettings.AUTO:
            return _IndexSettings.AUTO
        try:
            if isinstance(value, bool) or isinstance(value, float):
                raise ValueError
            number = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            number = -1
        if not 0 <= number <= _IndexSettings.MAX_WORKERS:
            raise _InvalidSettingValueError(
                f"The number of workers must be 'auto' or a whole number from 0 to "
                f"{_IndexSettings.MAX_WORKERS}, not {value!r}.",
                "Use 0 to index one file at a time on the calling thread.",
            )
        return number

    @staticmethod
    def get_workers(session: Session) -> int | str:
        """How many files are indexed at once: `auto` unless changed."""
        value = _Settings.get(session, _IndexSettings.WORKERS_KEY)
        if value is None:
            return _IndexSettings.AUTO
        try:
            return _IndexSettings.parse_workers(value)
        except _InvalidSettingValueError:
            return _IndexSettings.AUTO

    @staticmethod
    def set_workers(session: Session, value: object) -> None:
        _Settings.set(session, _IndexSettings.WORKERS_KEY, str(_IndexSettings.parse_workers(value)))

    @staticmethod
    def reset_workers(session: Session) -> None:
        _Settings.reset(session, _IndexSettings.WORKERS_KEY)

    @staticmethod
    def get_retry_attempts(session: Session) -> int:
        """How many times a failed file is tried again within a run. 3 unless changed."""
        value = _Settings.get(session, _IndexSettings.RETRY_ATTEMPTS_KEY)
        try:
            number = int(value) if value is not None else _IndexSettings.DEFAULT_RETRY_ATTEMPTS
        except ValueError:
            return _IndexSettings.DEFAULT_RETRY_ATTEMPTS
        return number if number >= 0 else _IndexSettings.DEFAULT_RETRY_ATTEMPTS

    @staticmethod
    def set_retry_attempts(session: Session, attempts: int) -> None:
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise _InvalidSettingValueError(
                f"The retry attempts must be a whole number of 0 or more, not {attempts!r}.",
                "Use 0 to try each file once.",
            )
        _Settings.set(session, _IndexSettings.RETRY_ATTEMPTS_KEY, str(attempts))

    @staticmethod
    def reset_retry_attempts(session: Session) -> None:
        _Settings.reset(session, _IndexSettings.RETRY_ATTEMPTS_KEY)

    @staticmethod
    def get_stability_check_seconds(session: Session) -> float:
        """How long to wait to be sure a file has stopped changing before indexing it. 1 second
        unless changed; 0 skips the check."""
        value = _Settings.get(session, _IndexSettings.STABILITY_CHECK_KEY)
        try:
            seconds = (
                float(value)
                if value is not None
                else _IndexSettings.DEFAULT_STABILITY_CHECK_SECONDS
            )
        except ValueError:
            return _IndexSettings.DEFAULT_STABILITY_CHECK_SECONDS
        return seconds if seconds >= 0 else _IndexSettings.DEFAULT_STABILITY_CHECK_SECONDS

    @staticmethod
    def set_stability_check_seconds(session: Session, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds < 0:
            raise _InvalidSettingValueError(
                f"The stability check must be a number of seconds of 0 or more, not {seconds!r}.",
                "Use 0 to turn the check off.",
            )
        _Settings.set(session, _IndexSettings.STABILITY_CHECK_KEY, repr(float(seconds)))

    @staticmethod
    def reset_stability_check_seconds(session: Session) -> None:
        _Settings.reset(session, _IndexSettings.STABILITY_CHECK_KEY)


class _LanguageSettings:
    DISABLED_KEY = "languages_disabled"
    DEFAULT_KEY = "languages_default"
    SEPARATOR = ","

    @staticmethod
    def _read(session: Session, key: str) -> list[str]:
        value = _Settings.get(session, key) or ""
        return [item for item in value.split(_LanguageSettings.SEPARATOR) if item]

    @staticmethod
    def _write(session: Session, key: str, ids: list[str]) -> None:
        if ids:
            _Settings.set(session, key, _LanguageSettings.SEPARATOR.join(ids))
        else:
            _Settings.reset(session, key)

    @staticmethod
    def get_disabled(session: Session) -> list[str]:
        """The language ids the user has switched off. Languages not listed here are on."""
        return _LanguageSettings._read(session, _LanguageSettings.DISABLED_KEY)

    @staticmethod
    def set_disabled(session: Session, ids: list[str]) -> None:
        _LanguageSettings._write(session, _LanguageSettings.DISABLED_KEY, ids)

    @staticmethod
    def get_default(session: Session) -> list[str]:
        """The language ids saved as the default for sources with none of their own (may be
        empty: then the system default applies)."""
        return _LanguageSettings._read(session, _LanguageSettings.DEFAULT_KEY)

    @staticmethod
    def set_default(session: Session, ids: list[str]) -> None:
        _LanguageSettings._write(session, _LanguageSettings.DEFAULT_KEY, ids)


class _FileTypeSettings:
    DISABLED_KEY = "file_types_disabled"
    SEPARATOR = ","

    @staticmethod
    def get_disabled(session: Session) -> list[str]:
        """The file type ids the user has switched off. File types not listed here are on."""
        value = _Settings.get(session, _FileTypeSettings.DISABLED_KEY) or ""
        return [item for item in value.split(_FileTypeSettings.SEPARATOR) if item]

    @staticmethod
    def set_disabled(session: Session, ids: list[str]) -> None:
        if ids:
            _Settings.set(session, _FileTypeSettings.DISABLED_KEY, _FileTypeSettings.SEPARATOR.join(ids))
        else:
            _Settings.reset(session, _FileTypeSettings.DISABLED_KEY)


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


class _MetricsSettings:
    OPT_IN_KEY = "metrics_opt_in"
    OPTED_IN_ON_KEY = "metrics_opted_in_on"
    INSTALL_ID_KEY = "metrics_install_id"
    LAST_SENT_KEY = "metrics_last_sent_at"
    SENT_THROUGH_KEY = "metrics_sent_through"

    @staticmethod
    def get_opt_in(session: Session) -> bool:
        """Whether anonymous usage metrics are shared. Off unless the user turned it on."""
        return _Settings.get(session, _MetricsSettings.OPT_IN_KEY) == "1"

    @staticmethod
    def set_opt_in(session: Session, on: bool) -> None:
        if not isinstance(on, bool):
            raise _InvalidSettingValueError(
                f"Metrics sharing is on or off (True or False), not {on!r}."
            )
        if on == _MetricsSettings.get_opt_in(session):
            return
        _Settings.set(session, _MetricsSettings.OPT_IN_KEY, "1" if on else "0")
        if on:
            _Settings.set(session, _MetricsSettings.OPTED_IN_ON_KEY, datetime.now(UTC).isoformat())

    @staticmethod
    def reset_opt_in(session: Session) -> None:
        _Settings.reset(session, _MetricsSettings.OPT_IN_KEY)

    @staticmethod
    def install_id(session: Session) -> str:
        """A random id, made on first use, that lets the collector delete this install's data. It
        isn't derived from the computer, the user or any licence."""
        value = _Settings.get(session, _MetricsSettings.INSTALL_ID_KEY)
        if not value:
            value = uuid.uuid4().hex
            _Settings.set(session, _MetricsSettings.INSTALL_ID_KEY, value)
        return value

    @staticmethod
    def sent_through(session: Session) -> str | None:
        """The last UTC day (YYYY-MM-DD) whose data has been sent."""
        return _Settings.get(session, _MetricsSettings.SENT_THROUGH_KEY)

    @staticmethod
    def new_install_id(session: Session) -> str:
        _Settings.reset(session, _MetricsSettings.INSTALL_ID_KEY)
        return _MetricsSettings.install_id(session)


class _ConfidenceSettings:
    KEY = "confidence_bands"
    DEFAULT = (70, 80, 90)  # percent: from `low`, from `medium`, from `high`

    @staticmethod
    def get_bands(session: Session) -> tuple[int, int, int]:
        """Where the confidence bands start, in percent: low, medium and high. Below the first is
        `unreliable`."""
        value = _Settings.get(session, _ConfidenceSettings.KEY)
        try:
            low, medium, high = (int(part) for part in (value or "").split(","))
            if 0 <= low < medium < high <= 100:
                return low, medium, high
        except ValueError:
            pass
        return _ConfidenceSettings.DEFAULT

    @staticmethod
    def set_bands(session: Session, low: int, medium: int, high: int) -> None:
        values = (low, medium, high)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in values) or not (
            0 <= low < medium < high <= 100
        ):
            raise _InvalidSettingValueError(
                f"The bands must be whole percentages, rising, from 0 to 100, not {values!r}.",
                "For example 70, 80, 90.",
            )
        _Settings.set(session, _ConfidenceSettings.KEY, f"{low},{medium},{high}")

    @staticmethod
    def reset_bands(session: Session) -> None:
        _Settings.reset(session, _ConfidenceSettings.KEY)


class _TierSettings:
    DEFAULT_KEY = "tiers_default"
    MIN_SIZE_KEY = "tiers_hybrid_min_size_factor"
    PHASES_KEY = "tiers_hybrid_phases"
    WAIT_KEY = "tiers_wait_timeout_minutes"
    JOB_PAGES_KEY = "tiers_max_job_pages"
    JOB_MB_KEY = "tiers_max_job_megabytes"
    TIER_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
    PHASES = ("quick", "moderate", "deep")
    DEFAULT_MIN_SIZE = 2.0
    DEFAULT_WAIT_MINUTES = 60
    DEFAULT_JOB_PAGES = 200
    DEFAULT_JOB_MB = 200

    @staticmethod
    def get_default(session: Session) -> str:
        """The processing tier used when a run doesn't name one. `local` unless changed."""
        value = _Settings.get(session, _TierSettings.DEFAULT_KEY)
        return value if value and _TierSettings.TIER_RE.match(value) else "local"

    @staticmethod
    def set_default(session: Session, tier: object) -> None:
        if not isinstance(tier, str) or not _TierSettings.TIER_RE.match(tier):
            raise _InvalidSettingValueError(
                f"{tier!r} isn't a processing tier id.", "For example local, github or hybrid."
            )
        _Settings.set(session, _TierSettings.DEFAULT_KEY, tier)

    @staticmethod
    def reset_default(session: Session) -> None:
        _Settings.reset(session, _TierSettings.DEFAULT_KEY)

    @staticmethod
    def _number(session: Session, key: str, default: float, cast, minimum: float) -> float:
        value = _Settings.get(session, key)
        try:
            number = cast(value) if value is not None else default
        except ValueError:
            return default
        return number if number >= minimum else default

    @staticmethod
    def _check(value: object, name: str, minimum: float, whole: bool) -> None:
        wrong = isinstance(value, bool) or not isinstance(value, int if whole else int | float)
        if wrong or value < minimum:
            kind = "a whole number" if whole else "a number"
            raise _InvalidSettingValueError(
                f"{name} must be {kind} of {minimum:g} or more, not {value!r}."
            )

    @staticmethod
    def get_min_size_factor(session: Session) -> float:
        """From what page size (against A4) hybrid sends a page to GitHub. 2 (A3) unless
        changed; 0 turns the size rule off."""
        return _TierSettings._number(
            session, _TierSettings.MIN_SIZE_KEY, _TierSettings.DEFAULT_MIN_SIZE, float, 0
        )

    @staticmethod
    def set_min_size_factor(session: Session, factor: float) -> None:
        _TierSettings._check(factor, "The size factor", 0, False)
        _Settings.set(session, _TierSettings.MIN_SIZE_KEY, repr(float(factor)))

    @staticmethod
    def get_phases(session: Session) -> list[str]:
        """The OCR phases hybrid sends to GitHub. None unless changed."""
        value = _Settings.get(session, _TierSettings.PHASES_KEY) or ""
        return [p for p in value.split(",") if p in _TierSettings.PHASES]

    @staticmethod
    def set_phases(session: Session, phases: object) -> list[str]:
        if isinstance(phases, str) or not hasattr(phases, "__iter__"):
            raise _InvalidSettingValueError('Phases are a list, for example ["moderate"].')
        chosen = [str(p).strip().lower() for p in phases]  # type: ignore[attr-defined]
        unknown = [p for p in chosen if p not in _TierSettings.PHASES]
        if unknown:
            raise _InvalidSettingValueError(
                f"Unknown phase {', '.join(map(repr, unknown))}.",
                f"Phases: {', '.join(_TierSettings.PHASES)}.",
            )
        chosen = list(dict.fromkeys(chosen))
        _Settings.set(session, _TierSettings.PHASES_KEY, ",".join(chosen))
        return chosen

    @staticmethod
    def get_wait_timeout_minutes(session: Session) -> int:
        """How long `index.run(wait=True)` waits for remote jobs. 60 minutes unless changed."""
        return int(
            _TierSettings._number(
                session, _TierSettings.WAIT_KEY, _TierSettings.DEFAULT_WAIT_MINUTES, int, 1
            )
        )

    @staticmethod
    def set_wait_timeout_minutes(session: Session, minutes: int) -> None:
        _TierSettings._check(minutes, "The timeout", 1, True)
        _Settings.set(session, _TierSettings.WAIT_KEY, str(minutes))

    @staticmethod
    def get_max_job_pages(session: Session) -> int:
        """The most pages one remote job holds. 200 unless changed."""
        return int(
            _TierSettings._number(
                session, _TierSettings.JOB_PAGES_KEY, _TierSettings.DEFAULT_JOB_PAGES, int, 1
            )
        )

    @staticmethod
    def set_max_job_pages(session: Session, pages: int) -> None:
        _TierSettings._check(pages, "The page limit", 1, True)
        _Settings.set(session, _TierSettings.JOB_PAGES_KEY, str(pages))

    @staticmethod
    def get_max_job_megabytes(session: Session) -> int:
        """The most payload (in MB) one remote job holds. 200 unless changed."""
        return int(
            _TierSettings._number(
                session, _TierSettings.JOB_MB_KEY, _TierSettings.DEFAULT_JOB_MB, int, 1
            )
        )

    @staticmethod
    def set_max_job_megabytes(session: Session, megabytes: int) -> None:
        _TierSettings._check(megabytes, "The size limit", 1, True)
        _Settings.set(session, _TierSettings.JOB_MB_KEY, str(megabytes))

    @staticmethod
    def reset(session: Session, key: str) -> None:
        _Settings.reset(session, key)


class _SearchSettings:
    ENGINE_KEY = "search_engine"
    CONTEXT_KEY = "search_snippet_context_chars"
    EXPORT_FORMAT_KEY = "search_export_format"
    EXPORT_FORMATS = ("json", "html")
    DEFAULT_EXPORT_FORMAT = "json"
    NORMALIZER_PREFIX = "search_normalize_"
    OPTION_PREFIX = "search_option_"
    OPTION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
    ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
    LEVEL_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
    DEFAULT_ENGINE = "all"
    DEFAULT_CONTEXT = 80
    MAX_CONTEXT = 2000
    AUTO = "auto"

    @staticmethod
    def option_key(engine: str, name: str) -> str:
        return f"{_SearchSettings.OPTION_PREFIX}{engine}.{name}"

    @staticmethod
    def get_option(session: Session, engine: str, name: str) -> str | None:
        """The default saved for an engine's option, or None (the engine's own applies)."""
        return _Settings.get(session, _SearchSettings.option_key(engine, name))

    @staticmethod
    def set_option(session: Session, engine: str, name: str, value: str) -> None:
        _Settings.set(session, _SearchSettings.option_key(engine, name), value)

    @staticmethod
    def reset_option(session: Session, engine: str, name: str) -> None:
        _Settings.reset(session, _SearchSettings.option_key(engine, name))

    @staticmethod
    def saved_options(session: Session) -> dict[str, dict[str, str]]:
        """Every saved engine option default, by engine id."""
        prefix = _SearchSettings.OPTION_PREFIX
        found: dict[str, dict[str, str]] = {}
        for row in session.scalars(select(_Setting).where(_Setting.key.like(f"{prefix}%"))):
            engine, _, name = row.key[len(prefix) :].partition(".")
            if engine and name:
                found.setdefault(engine, {})[name] = row.value
        return found

    @staticmethod
    def get_engine(session: Session) -> str:
        """The engine a search uses when it doesn't name one. `all` unless changed."""
        value = _Settings.get(session, _SearchSettings.ENGINE_KEY)
        return value if value and _SearchSettings.ID_RE.match(value) else "all"

    @staticmethod
    def set_engine(session: Session, engine: object) -> None:
        if not isinstance(engine, str) or not _SearchSettings.ID_RE.match(engine):
            raise _InvalidSettingValueError(
                f"{engine!r} isn't a search engine id.", "For example all, like or exact."
            )
        _Settings.set(session, _SearchSettings.ENGINE_KEY, engine)

    @staticmethod
    def get_context_chars(session: Session) -> int:
        """The characters of context a result shows either side of a match. 80 unless changed."""
        value = _Settings.get(session, _SearchSettings.CONTEXT_KEY)
        try:
            chars = int(value) if value is not None else _SearchSettings.DEFAULT_CONTEXT
        except ValueError:
            return _SearchSettings.DEFAULT_CONTEXT
        return (
            chars if 0 <= chars <= _SearchSettings.MAX_CONTEXT else _SearchSettings.DEFAULT_CONTEXT
        )

    @staticmethod
    def set_context_chars(session: Session, chars: object) -> None:
        if (
            isinstance(chars, bool)
            or not isinstance(chars, int)
            or not 0 <= chars <= _SearchSettings.MAX_CONTEXT
        ):
            raise _InvalidSettingValueError(
                f"The context must be a whole number from 0 to {_SearchSettings.MAX_CONTEXT}, "
                f"not {chars!r}."
            )
        _Settings.set(session, _SearchSettings.CONTEXT_KEY, str(chars))

    @staticmethod
    def get_export_format(session: Session) -> str:
        """The format an export is written in when it doesn't name one. `json` unless changed."""
        value = _Settings.get(session, _SearchSettings.EXPORT_FORMAT_KEY)
        if value in _SearchSettings.EXPORT_FORMATS:
            return value
        return _SearchSettings.DEFAULT_EXPORT_FORMAT

    @staticmethod
    def set_export_format(session: Session, value: object) -> None:
        if value not in _SearchSettings.EXPORT_FORMATS:
            raise _InvalidSettingValueError(
                f"{value!r} isn't an export format.",
                f"Formats: {', '.join(_SearchSettings.EXPORT_FORMATS)}.",
            )
        _Settings.set(session, _SearchSettings.EXPORT_FORMAT_KEY, str(value))

    @staticmethod
    def normalizer_key(normalizer: str) -> str:
        if not isinstance(normalizer, str) or not _SearchSettings.ID_RE.match(normalizer):
            raise _InvalidSettingValueError(f"{normalizer!r} isn't a normalizer id.")
        return f"{_SearchSettings.NORMALIZER_PREFIX}{normalizer}"

    @staticmethod
    def get_normalizer(session: Session, normalizer: str) -> str:
        """The level saved for a normalizer, or `auto` (each engine's own) if none."""
        value = _Settings.get(session, _SearchSettings.normalizer_key(normalizer))
        return value if value and _SearchSettings.LEVEL_RE.match(value) else "auto"

    @staticmethod
    def set_normalizer(session: Session, normalizer: str, level: object) -> None:
        key = _SearchSettings.normalizer_key(normalizer)
        if not isinstance(level, str) or not _SearchSettings.LEVEL_RE.match(level):
            raise _InvalidSettingValueError(f"{level!r} isn't a level of {normalizer}.")
        _Settings.set(session, key, level)

    @staticmethod
    def reset_normalizer(session: Session, normalizer: str) -> None:
        _Settings.reset(session, _SearchSettings.normalizer_key(normalizer))

    @staticmethod
    def reset(session: Session, key: str) -> None:
        _Settings.reset(session, key)
