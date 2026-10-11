"""VethuQ's settings: `VethuQ().settings`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from vethuq._db import _Database, _IntegrityCheck
from vethuq._errors import _InvalidSettingValueError
from vethuq._languages import _LanguageCatalog, _Languages
from vethuq._logs import _Log, _Logs
from vethuq._settings import (
    _ConfidenceSettings,
    _DatabaseSettings,
    _IndexSettings,
    _LanguageSettings,
    _LogSettings,
    _MetricsSettings,
    _OcrSettings,
    _SearchSettings,
    _SourceSettings,
    _TierSettings,
    _UpdateSettings,
)
from vethuq.enums import IntegrityCheckMode, LogLevel, UpdateCheckMode
from vethuq_addon_api import SearchOption

__all__ = [
    "ConfidenceSettings",
    "MetricsSettings",
    "DatabaseSettings",
    "IndexSettings",
    "LanguageSettings",
    "LogSettings",
    "OcrSettings",
    "SearchSettings",
    "Settings",
    "SourceSettings",
    "TierSettings",
    "UpdateSettings",
]


class SourceSettings:
    """Settings for sources.

    Not created directly: use `VethuQ().settings.sources`.
    """

    DEFAULT_REMOVED_RETENTION_MINUTES = _SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_removed_retention_minutes(self) -> int:
        """Minutes a removed source is kept before it is purged. 7 days unless changed."""
        with self._database.session() as session:
            return _SourceSettings.get_removed_retention_minutes(session)

    def set_removed_retention_minutes(self, minutes: int) -> None:
        """Keep removed sources for `minutes` before they are purged; 0 purges them at once.

        Raises `InvalidSettingValueError` if `minutes` isn't a whole number of 0 or more.
        """
        with self._database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, minutes)

    def reset_removed_retention_minutes(self) -> None:
        """Back to the default retention (7 days)."""
        with self._database.session() as session:
            _SourceSettings.reset_removed_retention_minutes(session)


class IndexSettings:
    """Settings for indexing.

    Not created directly: use `VethuQ().settings.index`.
    """

    MAX_WORKERS = _IndexSettings.MAX_WORKERS
    DEFAULT_RETRY_ATTEMPTS = _IndexSettings.DEFAULT_RETRY_ATTEMPTS
    DEFAULT_STABILITY_CHECK_SECONDS = _IndexSettings.DEFAULT_STABILITY_CHECK_SECONDS

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_workers(self) -> int | str:
        """How many files are indexed at once: `"auto"` (sized to the machine) unless changed."""
        with self._database.session() as session:
            return _IndexSettings.get_workers(session)

    def set_workers(self, workers: int | str) -> None:
        """Index `workers` files at once: `"auto"`, or 0 to 8 (0 uses the calling thread alone).

        Raises `InvalidSettingValueError` for anything else.
        """
        with self._database.session() as session:
            _IndexSettings.set_workers(session, workers)

    def reset_workers(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_workers(session)

    def get_stale_lock(self) -> str:
        """What a new run does about a run left behind by a process that ended without finishing:
        `auto` (the default) and `enable` fail it and carry on; `disable` refuses to start (the
        run stays, with its files, until `index.clear_stale()`)."""
        with self._database.session() as session:
            return _IndexSettings.get_stale_lock(session)

    def set_stale_lock(self, mode: str) -> str:
        """Raises `InvalidSettingValueError` unless `mode` is `auto`, `enable` or `disable`."""
        with self._database.session() as session:
            return _IndexSettings.set_stale_lock(session, mode)

    def reset_stale_lock(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_stale_lock(session)

    def get_retry_attempts(self) -> int:
        """How many times a failed file is tried again within a run. 3 unless changed."""
        with self._database.session() as session:
            return _IndexSettings.get_retry_attempts(session)

    def set_retry_attempts(self, attempts: int) -> None:
        """Try a failed file again up to `attempts` times; 0 tries each file once.

        Raises `InvalidSettingValueError` unless it is a whole number of 0 or more.
        """
        with self._database.session() as session:
            _IndexSettings.set_retry_attempts(session, attempts)

    def reset_retry_attempts(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_retry_attempts(session)

    def get_stability_check_seconds(self) -> float:
        """How long a run waits to be sure files have stopped changing. 1 second unless changed."""
        with self._database.session() as session:
            return _IndexSettings.get_stability_check_seconds(session)

    def set_stability_check_seconds(self, seconds: float) -> None:
        """Wait `seconds` before indexing files that may still be being written; 0 turns it off.

        Raises `InvalidSettingValueError` unless it is 0 or more.
        """
        with self._database.session() as session:
            _IndexSettings.set_stability_check_seconds(session, seconds)

    def reset_stability_check_seconds(self) -> None:
        with self._database.session() as session:
            _IndexSettings.reset_stability_check_seconds(session)


class OcrSettings:
    """Settings for OCR.

    Not created directly: use `VethuQ().settings.ocr`.
    """

    ENGINES = _OcrSettings.ENGINES

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_engine(self) -> str:
        """How far indexing reads: `"quick"` (upright text) unless changed. `"moderate"` also reads
        every page that needed OCR at 90, 180 and 270 degrees, and `"deep"` also every other
        multiple of 15 degrees; each needs its add-on (`vethuq-addon-ocr-moderate`, `-deep`). The
        picture a Markdown file links to are read from `"moderate"`."""
        with self._database.session() as session:
            return _OcrSettings.get_engine(session)

    def set_engine(self, engine: str) -> str:
        """Go as far as `engine` (`"quick"`, `"moderate"` or `"deep"`) and return it.

        Raises `InvalidSettingValueError` for anything else."""
        with self._database.session() as session:
            return _OcrSettings.set_engine(session, engine)

    def reset_engine(self) -> None:
        with self._database.session() as session:
            _OcrSettings.reset_engine(session)

    def get_gpu(self) -> bool:
        """Whether OCR engines are asked to use the GPU. `False` unless changed. An engine that
        can't use one reads on the CPU instead (and VethuQ says so in the log). Takes effect for
        engines started after the change."""
        with self._database.session() as session:
            return _OcrSettings.get_gpu(session)

    def set_gpu(self, enabled: bool) -> bool:
        """Ask OCR engines to use the GPU (or not). Raises `InvalidSettingValueError` unless
        `enabled` is `True` or `False`."""
        with self._database.session() as session:
            return _OcrSettings.set_gpu(session, enabled)

    def reset_gpu(self) -> None:
        with self._database.session() as session:
            _OcrSettings.reset_gpu(session)


class LanguageSettings:
    """Settings for languages.

    Not created directly: use `VethuQ().settings.languages`.
    """

    def __init__(self, database: _Database, catalog: _LanguageCatalog) -> None:
        self._database = database
        self._catalog = catalog

    def get_languages(self) -> list[str]:
        """The language ids a source with none of its own is read in. The system default
        (English) unless changed; a saved language that is no longer usable is left out."""
        with self._database.session() as session:
            return _Languages.default_ids(session, self._catalog.specs())

    def set_languages(self, languages: list[str]) -> list[str]:
        """Read sources with no languages of their own in `languages`, and return them.

        Raises `InvalidSettingValueError` for an empty list and `LanguageUnavailableError` for a
        language that is unknown, unavailable or disabled.
        """
        with self._database.session() as session:
            return _Languages.set_default_ids(session, self._catalog.specs(), languages)

    def reset_languages(self) -> None:
        """Back to the system default (English)."""
        with self._database.session() as session:
            _LanguageSettings.set_default(session, [])


class LogSettings:
    """Settings for the logs.

    Not created directly: use `VethuQ().settings.logs`. A change takes effect at once for
    logs already being written.
    """

    DEFAULT_LEVEL = _Log.DEFAULT_LEVEL
    DEFAULT_RETENTION_DAYS = _Log.DEFAULT_RETENTION_DAYS

    def __init__(self, database: _Database) -> None:
        self._database = database

    def _apply(self) -> None:
        _Logs.reconfigure(self._database.db_path)

    def get_level(self) -> LogLevel:
        """How much the logs record: a `LogLevel`. `INFO` unless changed."""
        with self._database.session() as session:
            return _LogSettings.get_level(session)

    def set_level(self, level: LogLevel | str) -> None:
        """Record entries at or above this level. Raises `InvalidSettingValueError` for a
        value that isn't a `LogLevel`."""
        with self._database.session() as session:
            _LogSettings.set_level(session, level)
        self._apply()

    def reset_level(self) -> None:
        """Back to the default level (`INFO`)."""
        with self._database.session() as session:
            _LogSettings.reset_level(session)
        self._apply()

    def get_retention_days(self) -> int:
        """How many days of daily log files are kept. 15 unless changed."""
        with self._database.session() as session:
            return _LogSettings.get_retention_days(session)

    def set_retention_days(self, days: int) -> None:
        """Keep `days` days of log files. Raises `InvalidSettingValueError` unless `days` is
        a whole number of at least 1."""
        with self._database.session() as session:
            _LogSettings.set_retention_days(session, days)
        self._apply()

    def reset_retention_days(self) -> None:
        """Back to the default retention (15 days)."""
        with self._database.session() as session:
            _LogSettings.reset_retention_days(session)
        self._apply()


class UpdateSettings:
    """Settings for the update check: whether it runs, and what the user chose to ignore.

    Not created directly: use `VethuQ().settings.updates`.
    """

    ENV_VAR = _UpdateSettings.ENV_VAR
    DEFAULT_CHECK = _UpdateSettings.DEFAULT_CHECK
    DEFAULT_SNOOZE_DAYS = _UpdateSettings.DEFAULT_SNOOZE_DAYS

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_check(self) -> UpdateCheckMode:
        """What the update check does, as an `UpdateCheckMode`: `ON` (the default) checks and
        offers to update, `NOTIFY_ONLY` checks and only tells you, `OFF` never checks.

        This is the saved setting; `disabled_by_environment()` says whether `VETHUQ_UPDATE_CHECK`
        overrides it.
        """
        with self._database.session() as session:
            return _UpdateSettings.get_check(session)

    def set_check(self, mode: UpdateCheckMode | str) -> None:
        """Set what the update check does. Raises `InvalidSettingValueError` for a value that
        isn't an `UpdateCheckMode`."""
        with self._database.session() as session:
            _UpdateSettings.set_check(session, mode)

    def reset_check(self) -> None:
        """Back to the default (`ON`)."""
        with self._database.session() as session:
            _UpdateSettings.reset_check(session)

    @staticmethod
    def disabled_by_environment() -> bool:
        """Whether the environment variable `VETHUQ_UPDATE_CHECK` (`off`, `0`, `false`, `no`,
        `disable` or `disabled`) switches the check off whatever the setting says."""
        return _UpdateSettings.disabled_by_environment()

    def get_snoozed_until(self) -> datetime | None:
        """When "remind me later" ends (UTC), or None when the notice isn't snoozed."""
        with self._database.session() as session:
            until = _UpdateSettings.get_snoozed_until(session)
        return datetime.fromtimestamp(until, UTC) if until is not None else None

    def snooze(self, days: float = DEFAULT_SNOOZE_DAYS) -> None:
        """Hide the update notice for `days` days (1 by default). Raises
        `InvalidSettingValueError` unless `days` is a number above 0."""
        with self._database.session() as session:
            _UpdateSettings.snooze(session, days)

    def clear_snooze(self) -> None:
        """Show the update notice again."""
        with self._database.session() as session:
            _UpdateSettings.clear_snooze(session)

    def get_skipped_version(self) -> str | None:
        """The version the user chose to skip, or None. A newer version is announced again."""
        with self._database.session() as session:
            return _UpdateSettings.get_skipped_version(session)

    def skip_version(self, version: str) -> None:
        """Stop announcing this version (only this one). Raises `InvalidSettingValueError` for
        an empty version."""
        with self._database.session() as session:
            _UpdateSettings.skip_version(session, version)

    def clear_skip(self) -> None:
        """Announce every version again."""
        with self._database.session() as session:
            _UpdateSettings.clear_skip(session)


class DatabaseSettings:
    """Settings for the database.

    Not created directly: use `VethuQ().settings.database`. They are read when the database is
    opened, so a change applies the next time a client opens it.
    """

    DEFAULT_INTEGRITY_CHECK = _IntegrityCheck.DEFAULT_MODE
    DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES = _IntegrityCheck.DEFAULT_INTERVAL_MINUTES

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_integrity_check(self) -> IntegrityCheckMode:
        """When the integrity check runs by itself, as an `IntegrityCheckMode`: `AUTO` (the
        default) when the database is opened, at most once per interval; `ENABLE` every time it is
        opened; `DISABLE` never (`client.db.integrity_check()` still works)."""
        with self._database.session() as session:
            return _DatabaseSettings.get_integrity_check(session)

    def set_integrity_check(self, mode: IntegrityCheckMode | str) -> None:
        """Set when the integrity check runs by itself. Raises `InvalidSettingValueError` for a
        value that isn't an `IntegrityCheckMode`."""
        with self._database.session() as session:
            _DatabaseSettings.set_integrity_check(session, mode)

    def reset_integrity_check(self) -> None:
        """Back to the default (`AUTO`)."""
        with self._database.session() as session:
            _DatabaseSettings.reset_integrity_check(session)

    def get_integrity_check_interval_minutes(self) -> int:
        """Minutes between automatic checks in `AUTO` mode. 1 day unless changed."""
        with self._database.session() as session:
            return _DatabaseSettings.get_integrity_check_interval_minutes(session)

    def set_integrity_check_interval_minutes(self, minutes: int) -> None:
        """Check at most once per `minutes` in `AUTO` mode. Raises `InvalidSettingValueError`
        unless `minutes` is a whole number of at least 1."""
        with self._database.session() as session:
            _DatabaseSettings.set_integrity_check_interval_minutes(session, minutes)

    def reset_integrity_check_interval_minutes(self) -> None:
        """Back to the default interval (1 day)."""
        with self._database.session() as session:
            _DatabaseSettings.reset_integrity_check_interval_minutes(session)


class MetricsSettings:
    """Settings for sharing anonymous usage metrics.

    Not created directly: use `VethuQ().settings.metrics`. `VethuQ().metrics` is the usual way to
    turn sharing on or off.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_opt_in(self) -> bool:
        """Whether metrics are shared. Off unless you turned it on."""
        with self._database.session() as session:
            return _MetricsSettings.get_opt_in(session)

    def set_opt_in(self, on: bool) -> None:
        """Turn sharing on or off. Raises `InvalidSettingValueError` unless `on` is a bool."""
        with self._database.session() as session:
            _MetricsSettings.set_opt_in(session, on)

    def reset_opt_in(self) -> None:
        with self._database.session() as session:
            _MetricsSettings.reset_opt_in(session)


class ConfidenceSettings:
    """Where the confidence bands start.

    Not created directly: use `VethuQ().settings.confidence`. A page is `high`, `medium`, `low` or
    `unreliable` by its confidence in percent; by default 90, 80 and 70.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_bands(self) -> tuple[int, int, int]:
        """The percentages the `low`, `medium` and `high` bands start at. (70, 80, 90) unless
        changed; below the first is `unreliable`."""
        with self._database.session() as session:
            return _ConfidenceSettings.get_bands(session)

    def set_bands(self, low: int, medium: int, high: int) -> None:
        """Change the bands: whole percentages, rising, from 0 to 100. Raises
        `InvalidSettingValueError` for anything else."""
        with self._database.session() as session:
            _ConfidenceSettings.set_bands(session, low, medium, high)

    def reset_bands(self) -> None:
        with self._database.session() as session:
            _ConfidenceSettings.reset_bands(session)


class TierSettings:
    """Settings for processing tiers.

    Not created directly: use `VethuQ().settings.tiers`. The default tier itself is chosen with
    `VethuQ().tiers.use(...)`; these are the rest.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_min_size_factor(self) -> float:
        """From what page size, against A4, hybrid sends a page to GitHub. 2 (A3) unless
        changed; 0 turns the size rule off."""
        with self._database.session() as session:
            return _TierSettings.get_min_size_factor(session)

    def set_min_size_factor(self, factor: float) -> None:
        """Raises `InvalidSettingValueError` unless it is a number of 0 or more."""
        with self._database.session() as session:
            _TierSettings.set_min_size_factor(session, factor)

    def reset_min_size_factor(self) -> None:
        with self._database.session() as session:
            _TierSettings.reset(session, _TierSettings.MIN_SIZE_KEY)

    def get_phases(self) -> list[str]:
        """The OCR phases hybrid sends to GitHub (`moderate`, `deep`). None unless changed."""
        with self._database.session() as session:
            return _TierSettings.get_phases(session)

    def set_phases(self, phases: list[str]) -> list[str]:
        """Choose the phases (`quick`, `moderate`, `deep`) hybrid sends to GitHub and return
        them. Raises `InvalidSettingValueError` for anything else."""
        with self._database.session() as session:
            return _TierSettings.set_phases(session, phases)

    def reset_phases(self) -> None:
        with self._database.session() as session:
            _TierSettings.reset(session, _TierSettings.PHASES_KEY)

    def get_wait_timeout_minutes(self) -> int:
        """How long `index.run(wait=True)` waits for remote jobs. 60 minutes unless changed."""
        with self._database.session() as session:
            return _TierSettings.get_wait_timeout_minutes(session)

    def set_wait_timeout_minutes(self, minutes: int) -> None:
        with self._database.session() as session:
            _TierSettings.set_wait_timeout_minutes(session, minutes)

    def reset_wait_timeout_minutes(self) -> None:
        with self._database.session() as session:
            _TierSettings.reset(session, _TierSettings.WAIT_KEY)

    def get_max_job_pages(self) -> int:
        """The most pages one remote job holds. 200 unless changed."""
        with self._database.session() as session:
            return _TierSettings.get_max_job_pages(session)

    def set_max_job_pages(self, pages: int) -> None:
        with self._database.session() as session:
            _TierSettings.set_max_job_pages(session, pages)

    def reset_max_job_pages(self) -> None:
        with self._database.session() as session:
            _TierSettings.reset(session, _TierSettings.JOB_PAGES_KEY)

    def get_max_job_megabytes(self) -> int:
        """The most payload, in MB, one remote job holds. 200 unless changed."""
        with self._database.session() as session:
            return _TierSettings.get_max_job_megabytes(session)

    def set_max_job_megabytes(self, megabytes: int) -> None:
        with self._database.session() as session:
            _TierSettings.set_max_job_megabytes(session, megabytes)

    def reset_max_job_megabytes(self) -> None:
        with self._database.session() as session:
            _TierSettings.reset(session, _TierSettings.JOB_MB_KEY)


class SearchSettings:
    """Settings for searching.

    Not created directly: use `VethuQ().settings.search`. What counts as "the same character" is a
    setting per normalizer: `auto` (the default) lets each search engine use its own level (`like`
    ignores case, `exact` matches it), anything else is one of the normalizer's levels and applies
    to every engine that takes a saved level.
    """

    def __init__(
        self,
        database: _Database,
        engines: Callable[[], list[str]],
        normalizers: Callable[[], dict[str, tuple[str, ...]]],
        options: Callable[[], dict[str, tuple[SearchOption, ...]]] = dict,
    ) -> None:
        self._database = database
        self._engines = engines
        self._normalizers = normalizers
        self._options = options

    def get_engine(self) -> str:
        """The engine a search uses when it doesn't name one: `all`, or an engine id."""
        with self._database.session() as session:
            return _SearchSettings.get_engine(session)

    def set_engine(self, engine: str) -> None:
        """Raises `InvalidSettingValueError` unless it is `all` or an installed engine."""
        known = ["all", "hybrid", *self._engines()]
        if engine not in known:
            raise _InvalidSettingValueError(
                f"{engine!r} isn't a search engine.", f"Engines: {', '.join(known)}."
            )
        with self._database.session() as session:
            _SearchSettings.set_engine(session, engine)

    def reset_engine(self) -> None:
        with self._database.session() as session:
            _SearchSettings.reset(session, _SearchSettings.ENGINE_KEY)

    def get_snippet_context_chars(self) -> int:
        """The characters of context shown either side of a match. 80 unless changed."""
        with self._database.session() as session:
            return _SearchSettings.get_context_chars(session)

    def set_snippet_context_chars(self, chars: int) -> None:
        """Raises `InvalidSettingValueError` unless it is a whole number from 0 to 2000."""
        with self._database.session() as session:
            _SearchSettings.set_context_chars(session, chars)

    def reset_snippet_context_chars(self) -> None:
        with self._database.session() as session:
            _SearchSettings.reset(session, _SearchSettings.CONTEXT_KEY)

    def get_export_format(self) -> str:
        """The format `search.export`, `sources.export` and `sources.export_files` write when they
        aren't told one: `json` (the default) or `html`."""
        with self._database.session() as session:
            return _SearchSettings.get_export_format(session)

    def set_export_format(self, format: str) -> None:
        """Raises `InvalidSettingValueError` unless it is `json` or `html`."""
        with self._database.session() as session:
            _SearchSettings.set_export_format(session, str(format).strip().lower())

    def reset_export_format(self) -> None:
        with self._database.session() as session:
            _SearchSettings.reset(session, _SearchSettings.EXPORT_FORMAT_KEY)

    def _option(self, engine: str, name: str) -> SearchOption:
        declared = self._options()
        if engine not in declared:
            known = ", ".join(sorted(declared)) or "none"
            raise _InvalidSettingValueError(
                f"The {engine!r} engine has no options.", f"Engines with options: {known}."
            )
        found = next((o for o in declared[engine] if o.name == name), None)
        if found is None:
            names = ", ".join(o.name for o in declared[engine])
            raise _InvalidSettingValueError(
                f"The {engine} engine has no option {name!r}.", f"Options: {names}."
            )
        return found

    def get_option(self, engine: str, name: str) -> str:
        """The default an engine option has in searches: the value saved, else the engine's own.
        Raises `InvalidSettingValueError` for an engine or option that isn't installed."""
        option = self._option(engine, name)
        with self._database.session() as session:
            saved = _SearchSettings.get_option(session, engine, name)
        return saved if saved is not None else option.default

    def set_option(self, engine: str, name: str, value: str) -> None:
        """Save a default for an engine's option (`fuzzy`, `threshold`, `loose`). A search's own
        `options=` still wins. Raises `InvalidSettingValueError` for an engine or option that
        isn't installed, or a value outside the option's choices."""
        option = self._option(engine, name)
        if not isinstance(value, str) or not value:
            raise _InvalidSettingValueError(f"{engine}.{name} needs a value, not {value!r}.")
        if option.choices and value not in option.choices:
            raise _InvalidSettingValueError(
                f"{engine}.{name} must be one of {', '.join(option.choices)}, not {value!r}."
            )
        with self._database.session() as session:
            _SearchSettings.set_option(session, engine, name, value)

    def reset_option(self, engine: str, name: str) -> None:
        """Back to the engine's own default."""
        self._option(engine, name)
        with self._database.session() as session:
            _SearchSettings.reset_option(session, engine, name)

    def get_normalizer(self, normalizer: str) -> str:
        """The level saved for a normalizer (`case`, `unicode`, ...), or `auto`."""
        with self._database.session() as session:
            return _SearchSettings.get_normalizer(session, normalizer)

    def set_normalizer(self, normalizer: str, level: str) -> None:
        """Save a level for an installed normalizer. `auto` lets each engine use its own.
        Raises `InvalidSettingValueError` for a normalizer or level that isn't installed."""
        installed = self._normalizers()
        if normalizer not in installed:
            known = ", ".join(sorted(installed)) or "none"
            raise _InvalidSettingValueError(
                f"There is no normalizer {normalizer!r}.", f"Normalizers: {known}."
            )
        if level != "auto" and level not in installed[normalizer]:
            raise _InvalidSettingValueError(
                f"{normalizer} must be auto or one of {', '.join(installed[normalizer])}, "
                f"not {level!r}."
            )
        with self._database.session() as session:
            _SearchSettings.set_normalizer(session, normalizer, level)

    def reset_normalizer(self, normalizer: str) -> None:
        with self._database.session() as session:
            _SearchSettings.reset_normalizer(session, normalizer)

    def get_case(self) -> str:
        """`auto`, `match` or `ignore`: whether upper and lower case are the same letter."""
        return self.get_normalizer("case")

    def set_case(self, level: str) -> None:
        self.set_normalizer("case", level)

    def reset_case(self) -> None:
        self.reset_normalizer("case")

    def get_unicode(self) -> str:
        """`auto`, `off`, `basic` or `full`: how differently written characters are treated."""
        return self.get_normalizer("unicode")

    def set_unicode(self, level: str) -> None:
        self.set_normalizer("unicode", level)

    def reset_unicode(self) -> None:
        self.reset_normalizer("unicode")


class Settings:
    """VethuQ's settings, grouped by feature.

    Not created directly: use `VethuQ().settings`.
    """

    def __init__(
        self,
        database: _Database,
        catalog: _LanguageCatalog,
        engines: Callable[[], list[str]] = list,
        normalizers: Callable[[], dict[str, tuple[str, ...]]] = dict,
        options: Callable[[], dict[str, tuple[SearchOption, ...]]] = dict,
    ) -> None:
        self.search = SearchSettings(database, engines, normalizers, options)
        self.sources = SourceSettings(database)
        self.languages = LanguageSettings(database, catalog)
        self.index = IndexSettings(database)
        self.ocr = OcrSettings(database)
        self.tiers = TierSettings(database)
        self.metrics = MetricsSettings(database)
        self.confidence = ConfidenceSettings(database)
        self.logs = LogSettings(database)
        self.updates = UpdateSettings(database)
        self.database = DatabaseSettings(database)
