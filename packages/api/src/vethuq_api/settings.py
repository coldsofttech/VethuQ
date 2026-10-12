"""The settings the interface shows: what each is, how it is edited and how it is saved.

The core keeps the values (`client.settings.<area>`); this module adds what the core does not say:
a label, a description, the kind of control, and the allowed values. Settings are grouped into
sections, one section per page of the settings screen.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vethuq_api.setting_spec import (  # noqa: F401  (re-exported for callers and tests)
    BANDS,
    BOOLEAN,
    CHOICE,
    INTEGER,
    MULTI,
    NUMBER,
    PATH,
    TEXT,
    InvalidSettingError,
    SettingNotFoundError,
    Spec,
)
from vethuq_api.settings_dynamic import addon_specs, search_specs

_NEXT_RUN = "Applies from the next indexing run."


def _workers_options(_client: Any) -> list[dict[str, object]]:
    from vethuq.settings import IndexSettings

    options: list[dict[str, object]] = [
        {"value": "auto", "label": "Automatic (sized to this computer)"},
        {"value": 0, "label": "0: one file at a time, without extra threads"},
    ]
    options += [{"value": n, "label": str(n)} for n in range(1, IndexSettings.MAX_WORKERS + 1)]
    return options


def _stale_lock_options(_client: Any) -> list[dict[str, object]]:
    return [
        {"value": "auto", "label": "Automatic (recommended)"},
        {"value": "enable", "label": "Fail the leftover run and carry on"},
        {"value": "disable", "label": "Refuse to start until it is cleared"},
    ]


_OCR_DEPTHS = (
    ("quick", "Quick: upright text", ""),
    ("moderate", "Moderate: also pages rotated 90°, 180° and 270°", "vethuq-addon-ocr-moderate"),
    ("deep", "Deep: also every other multiple of 15°", "vethuq-addon-ocr-deep"),
)


def _ocr_depth_options(client: Any) -> list[dict[str, object]]:
    phases = {phase.id: phase for phase in client.ocr.phases.list()}
    options: list[dict[str, object]] = []
    for value, label, addon in _OCR_DEPTHS:
        phase = phases.get(value)
        available = phase is not None and phase.available
        reason = ""
        if not available:
            reason = (phase.reason if phase is not None else "") or f"Needs the {addon} add-on."
        options.append({"value": value, "label": label, "available": available, "reason": reason})
    return options


def _language_options(client: Any) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for language in client.languages.list_all():
        usable = language.available and language.enabled
        reason = ""
        if not usable:
            reason = language.reason or "This language is turned off."
        label = language.label
        if language.native_label and language.native_label != language.label:
            label = f"{language.label} ({language.native_label})"
        options.append(
            {"value": language.id, "label": label, "available": usable, "reason": reason}
        )
    return options


def _language_default(client: Any) -> list[str]:
    return [language.id for language in client.languages.list_all() if language.default]


def _tier_options(client: Any) -> list[dict[str, object]]:
    return [
        {"value": tier.id, "label": tier.label, "available": tier.available, "reason": tier.reason}
        for tier in client.tiers.list()
    ]


_HYBRID_PHASES = (
    ("moderate", "Moderate"),
    ("deep", "Deep"),
)


def _hybrid_phase_options(client: Any) -> list[dict[str, object]]:
    options = [{"value": value, "label": label} for value, label in _HYBRID_PHASES]
    # A phase set from the command line that this list does not offer stays visible and editable.
    offered = {value for value, _ in _HYBRID_PHASES}
    for value in client.settings.tiers.get_phases():
        if value not in offered:
            options.append({"value": value, "label": value.capitalize()})
    return options


def _text(value: Any) -> str:
    """An enum as its plain value (`LogLevel.INFO` as "info")."""
    return str(getattr(value, "value", value))


def _log_level_options(_client: Any) -> list[dict[str, object]]:
    return [
        {"value": "debug", "label": "Debug: everything, for troubleshooting"},
        {"value": "info", "label": "Info: normal activity"},
        {"value": "warning", "label": "Warning: warnings and errors"},
        {"value": "error", "label": "Error: errors only"},
    ]


def _update_check_options(_client: Any) -> list[dict[str, object]]:
    return [
        {"value": "on", "label": "On: check and offer to update"},
        {"value": "notify-only", "label": "Notify only: check and tell me"},
        {"value": "off", "label": "Off: never check"},
    ]


def _update_check_note(client: Any) -> str:
    from vethuq.settings import UpdateSettings

    if UpdateSettings.disabled_by_environment():
        return (
            f"The {UpdateSettings.ENV_VAR} environment variable switches update checks off, "
            "whatever this says."
        )
    return ""


def _snoozed_until(client: Any) -> str | None:
    until = client.settings.updates.get_snoozed_until()
    return until.isoformat() if until is not None else None


def _integrity_options(_client: Any) -> list[dict[str, object]]:
    return [
        {"value": "auto", "label": "Automatic: when the database opens, at most once per interval"},
        {"value": "enable", "label": "Every time the database opens"},
        {"value": "disable", "label": "Never by itself"},
    ]


def _engine_options(client: Any) -> list[dict[str, object]]:
    engines = client.search.engines()
    semantic = next((e for e in engines if e.id == "semantic"), None)
    options: list[dict[str, object]] = [{"value": "all", "label": "All engines"}]
    options.append(
        {
            "value": "hybrid",
            "label": "Hybrid: meaning plus a keyword engine",
            "available": semantic is not None and semantic.available,
            "reason": "Needs the semantic engine.",
        }
    )
    options += [
        {"value": e.id, "label": e.label, "available": e.available, "reason": e.reason}
        for e in engines
    ]
    return options


def _paths() -> Any:
    """The core's `Paths` (imported on use so this module loads without the core)."""
    from vethuq import Paths

    return Paths


def _data_location_lock(_client: Any) -> str:
    from vethuq import Paths

    if Paths.location_source() == "env":
        return f"The {Paths.ENV_VAR} environment variable sets this folder; change it there."
    return ""


def _relocate(_client: Any, value: Any, options: dict[str, Any]) -> None:
    from vethuq import Paths

    Paths.relocate(value, move=options.get("move", True))


def _platform_default() -> Any:
    """The data folder VethuQ uses when none was chosen.

    `Paths.default_data_root()` is meant to be this, but it reports the folder in use (the saved
    one after a move), so it cannot say where "default" is. The core's own helper can.
    """
    from vethuq._paths import _Paths

    return _Paths.platform_data_root()


def _reset_location(_client: Any, options: dict[str, Any]) -> None:
    """Back to the default folder. `Paths.reset_location(move=True)` forgets a saved location
    without moving the data (it compares the folder in use with itself), which would leave the data
    behind; so the data is moved first, and the saved location is forgotten after."""
    from vethuq import Paths

    if options.get("move", True) and Paths.location_source() == "saved":
        Paths.relocate(_platform_default(), move=True)
    Paths.reset_location(move=False)


def _path_errors() -> tuple[type[BaseException], ...]:
    from vethuq.errors import DataFolderNotWritableError

    return (ValueError, OSError, DataFolderNotWritableError)


def _default_data_folder(_client: Any) -> str:
    return str(_platform_default())


def _default_backups_folder(_client: Any) -> str:
    from vethuq import Paths

    return str(Paths.db_dir() / "backups")  # next to the database, unless a folder is chosen


def _specs() -> tuple[Spec, ...]:
    return (
        Spec(
            id="index.workers",
            section="indexing",
            label="Files indexed at once",
            description="How many files are read in parallel. More is faster but uses more of "
            "the computer.",
            kind=CHOICE,
            default="auto",
            read=lambda c: c.settings.index.get_workers(),
            write=lambda c, v: c.settings.index.set_workers(v),
            reset=lambda c: c.settings.index.reset_workers(),
            options=_workers_options,
            note=_NEXT_RUN,
        ),
        Spec(
            id="index.retry_attempts",
            section="indexing",
            label="Retries for a failed file",
            description="How many times a file that failed is tried again within a run. "
            "0 tries each file once.",
            kind=INTEGER,
            default=3,
            read=lambda c: c.settings.index.get_retry_attempts(),
            write=lambda c, v: c.settings.index.set_retry_attempts(v),
            reset=lambda c: c.settings.index.reset_retry_attempts(),
            minimum=0,
            note=_NEXT_RUN,
        ),
        Spec(
            id="ocr.engine",
            section="indexing",
            label="OCR depth",
            description="How far indexing reads pages that need OCR. Deeper reading finds more "
            "in rotated or skewed scans but takes longer.",
            kind=CHOICE,
            default="quick",
            read=lambda c: c.settings.ocr.get_engine(),
            write=lambda c, v: c.settings.ocr.set_engine(v),
            reset=lambda c: c.settings.ocr.reset_engine(),
            options=_ocr_depth_options,
            note=_NEXT_RUN,
        ),
        Spec(
            id="ocr.gpu",
            section="indexing",
            label="Use the graphics card for OCR",
            description="Ask OCR engines to use the GPU. An engine that cannot use one reads on "
            "the processor instead.",
            kind=BOOLEAN,
            default=False,
            read=lambda c: c.settings.ocr.get_gpu(),
            write=lambda c, v: c.settings.ocr.set_gpu(v),
            reset=lambda c: c.settings.ocr.reset_gpu(),
            note="Applies to OCR engines started after the change.",
        ),
        Spec(
            id="index.stability_check_seconds",
            section="indexing",
            label="Wait for files to stop changing",
            description="How long a run waits to be sure files are no longer being written. "
            "0 turns the wait off.",
            kind=NUMBER,
            default=1.0,
            read=lambda c: c.settings.index.get_stability_check_seconds(),
            write=lambda c, v: c.settings.index.set_stability_check_seconds(float(v)),
            reset=lambda c: c.settings.index.reset_stability_check_seconds(),
            minimum=0,
            unit="seconds",
            advanced=True,
            note=_NEXT_RUN,
        ),
        Spec(
            id="index.stale_lock",
            section="indexing",
            label="A run left behind by a crash",
            description="What a new run does when a previous run ended without finishing.",
            kind=CHOICE,
            default="auto",
            read=lambda c: c.settings.index.get_stale_lock(),
            write=lambda c, v: c.settings.index.set_stale_lock(v),
            reset=lambda c: c.settings.index.reset_stale_lock(),
            options=_stale_lock_options,
            advanced=True,
            note=_NEXT_RUN,
        ),
        Spec(
            id="location.data",
            section="general",
            group="Data",
            label="Data folder",
            description="Where VethuQ keeps its database, logs and other data.",
            kind=PATH,
            default=_default_data_folder,
            read=lambda c: _paths().data_root().__str__(),
            write=None,
            reset=None,
            write_with=_relocate,
            reset_with=_reset_location,
            moves=True,
            locked=_data_location_lock,
            catches=_path_errors(),
            note="Stop indexing before moving it.",
        ),
        Spec(
            id="location.backups",
            section="general",
            group="Data",
            label="Backups folder",
            description="Where database backups are kept. By default, next to the database.",
            kind=PATH,
            default=_default_backups_folder,
            read=lambda c: str(_paths().backups_dir()),
            write=lambda c, v: _paths().set_backups_dir(v),
            reset=lambda c: _paths().reset_backups_dir(),
            catches=_path_errors(),
        ),
        Spec(
            id="search.engine",
            section="search",
            group="Searching",
            label="Default search engine",
            description="The engine a search uses when it does not name one.",
            kind=CHOICE,
            default="all",
            read=lambda c: c.settings.search.get_engine(),
            write=lambda c, v: c.settings.search.set_engine(v),
            reset=lambda c: c.settings.search.reset_engine(),
            options=_engine_options,
        ),
        Spec(
            id="search.snippet_context_chars",
            section="search",
            group="Searching",
            label="Context around a match",
            description="How much text is shown on either side of a match in a result.",
            kind=INTEGER,
            default=80,
            read=lambda c: c.settings.search.get_snippet_context_chars(),
            write=lambda c, v: c.settings.search.set_snippet_context_chars(v),
            reset=lambda c: c.settings.search.reset_snippet_context_chars(),
            minimum=0,
            maximum=2000,
            unit="characters",
        ),
        Spec(
            id="search.export_format",
            section="search",
            group="Searching",
            label="Export format",
            description="The format exports are written in when none is chosen.",
            kind=CHOICE,
            default="json",
            read=lambda c: c.settings.search.get_export_format(),
            write=lambda c, v: c.settings.search.set_export_format(v),
            reset=lambda c: c.settings.search.reset_export_format(),
            options=lambda _c: [
                {"value": "json", "label": "JSON"},
                {"value": "html", "label": "HTML report"},
            ],
        ),
        Spec(
            id="languages.languages",
            section="general",
            group="Languages",
            label="Languages to read documents in",
            description="The languages a source is read in when it has none of its own. Choose at "
            "least one.",
            kind=MULTI,
            default=_language_default,
            read=lambda c: c.settings.languages.get_languages(),
            write=lambda c, v: c.settings.languages.set_languages(v),
            reset=lambda c: c.settings.languages.reset_languages(),
            options=_language_options,
            minimum=1,
            note="Applies to sources added or indexed from now on.",
        ),
        Spec(
            id="updates.check",
            section="general",
            group="Updates",
            label="Check for updates",
            description="Whether VethuQ looks for a newer version, and whether it offers to "
            "install it.",
            kind=CHOICE,
            default="on",
            read=lambda c: _text(c.settings.updates.get_check()),
            write=lambda c, v: c.settings.updates.set_check(v),
            reset=lambda c: c.settings.updates.reset_check(),
            options=_update_check_options,
            note=_update_check_note,
        ),
        Spec(
            id="metrics.opt_in",
            section="general",
            group="Privacy",
            label="Share anonymous usage metrics",
            description="Help improve VethuQ by sharing anonymous usage figures. Off unless you "
            "turn it on.",
            kind=BOOLEAN,
            default=False,
            read=lambda c: c.settings.metrics.get_opt_in(),
            write=lambda c, v: c.settings.metrics.set_opt_in(v),
            reset=lambda c: c.settings.metrics.reset_opt_in(),
        ),
        Spec(
            id="updates.skipped_version",
            section="general",
            group="Updates",
            label="Skipped update",
            description="The version you chose not to be told about. A newer version is announced "
            "again.",
            kind=TEXT,
            default=None,
            read=lambda c: c.settings.updates.get_skipped_version(),
            write=None,
            reset=lambda c: c.settings.updates.clear_skip(),
            advanced=True,
        ),
        Spec(
            id="updates.snoozed_until",
            section="general",
            group="Updates",
            label="Update notice snoozed until",
            description='When "remind me later" ends. Clearing it shows the notice again.',
            kind=TEXT,
            default=None,
            read=_snoozed_until,
            write=None,
            reset=lambda c: c.settings.updates.clear_snooze(),
            advanced=True,
        ),
        Spec(
            id="sources.removed_retention_minutes",
            section="sources",
            label="Keep a removed source for",
            description="How long a removed source stays recoverable before it is purged. "
            "0 purges it at once. The default is 7 days.",
            kind=INTEGER,
            default=10080,
            read=lambda c: c.settings.sources.get_removed_retention_minutes(),
            write=lambda c, v: c.settings.sources.set_removed_retention_minutes(v),
            reset=lambda c: c.settings.sources.reset_removed_retention_minutes(),
            minimum=0,
            unit="minutes",
        ),
        Spec(
            id="tiers.default",
            section="tiers",
            group="Where work is done",
            label="Processing tier",
            description="Where indexing work is done by default. A run can still choose its own "
            "tier.",
            kind=CHOICE,
            default="local",
            read=lambda c: c.tiers.current().id,
            write=lambda c, v: c.tiers.use(v),
            reset=lambda c: c.tiers.reset(),
            options=_tier_options,
        ),
        Spec(
            id="tiers.phases",
            section="tiers",
            group="Hybrid tier",
            label="OCR phases sent to GitHub",
            description="With the hybrid tier, the OCR phases that are done on GitHub instead of "
            "on this computer: Moderate also reads pages rotated 90°, 180° and 270°, Deep every "
            "other multiple of 15°.",
            kind=MULTI,
            default=[],
            read=lambda c: c.settings.tiers.get_phases(),
            write=lambda c, v: c.settings.tiers.set_phases(v),
            reset=lambda c: c.settings.tiers.reset_phases(),
            options=_hybrid_phase_options,
            minimum=0,
            note="Used by the hybrid tier.",
        ),
        Spec(
            id="tiers.min_size_factor",
            section="tiers",
            group="Hybrid tier",
            label="Smallest page sent to GitHub",
            description="With the hybrid tier, pages at least this large, against A4, are sent to "
            "GitHub. 2 means A3. 0 turns the size rule off.",
            kind=NUMBER,
            default=2.0,
            read=lambda c: c.settings.tiers.get_min_size_factor(),
            write=lambda c, v: c.settings.tiers.set_min_size_factor(float(v)),
            reset=lambda c: c.settings.tiers.reset_min_size_factor(),
            minimum=0,
            unit="times A4",
            note="Used by the hybrid tier.",
        ),
        Spec(
            id="tiers.max_job_pages",
            section="tiers",
            group="Remote jobs",
            label="Most pages in one remote job",
            description="A job that would hold more pages is split.",
            kind=INTEGER,
            default=200,
            read=lambda c: c.settings.tiers.get_max_job_pages(),
            write=lambda c, v: c.settings.tiers.set_max_job_pages(v),
            reset=lambda c: c.settings.tiers.reset_max_job_pages(),
            minimum=1,
            unit="pages",
            advanced=True,
        ),
        Spec(
            id="tiers.max_job_megabytes",
            section="tiers",
            group="Remote jobs",
            label="Largest remote job",
            description="A job whose files add up to more than this is split.",
            kind=INTEGER,
            default=200,
            read=lambda c: c.settings.tiers.get_max_job_megabytes(),
            write=lambda c, v: c.settings.tiers.set_max_job_megabytes(v),
            reset=lambda c: c.settings.tiers.reset_max_job_megabytes(),
            minimum=1,
            unit="MB",
            advanced=True,
        ),
        Spec(
            id="tiers.wait_timeout_minutes",
            section="tiers",
            group="Remote jobs",
            label="How long to wait for remote jobs",
            description="When a run is told to wait, how long it waits for remote jobs to finish "
            "before giving up.",
            kind=INTEGER,
            default=60,
            read=lambda c: c.settings.tiers.get_wait_timeout_minutes(),
            write=lambda c, v: c.settings.tiers.set_wait_timeout_minutes(v),
            reset=lambda c: c.settings.tiers.reset_wait_timeout_minutes(),
            minimum=1,
            unit="minutes",
            advanced=True,
        ),
        Spec(
            id="confidence.bands",
            section="results",
            label="Confidence bands",
            description="How sure OCR must be for a page to count as low, medium or high "
            "confidence. A page below the first number is unreliable.",
            kind=BANDS,
            default=[70, 80, 90],
            read=lambda c: list(c.settings.confidence.get_bands()),
            write=lambda c, v: c.settings.confidence.set_bands(*v),
            reset=lambda c: c.settings.confidence.reset_bands(),
            labels=("Low from", "Medium from", "High from"),
            minimum=0,
            maximum=100,
            unit="%",
        ),
        Spec(
            id="logs.level",
            section="system",
            group="Logs",
            label="Log detail",
            description="How much VethuQ writes to its log files.",
            kind=CHOICE,
            default="info",
            read=lambda c: _text(c.settings.logs.get_level()),
            write=lambda c, v: c.settings.logs.set_level(v),
            reset=lambda c: c.settings.logs.reset_level(),
            options=_log_level_options,
            note="Takes effect at once.",
        ),
        Spec(
            id="logs.retention_days",
            section="system",
            group="Logs",
            label="Keep log files for",
            description="Older daily log files are deleted.",
            kind=INTEGER,
            default=15,
            read=lambda c: c.settings.logs.get_retention_days(),
            write=lambda c, v: c.settings.logs.set_retention_days(v),
            reset=lambda c: c.settings.logs.reset_retention_days(),
            minimum=1,
            unit="days",
            note="Takes effect at once.",
        ),
        Spec(
            id="database.integrity_check",
            section="system",
            group="Database",
            label="Check the database for damage",
            description="When VethuQ checks that its database is intact. A check can always be "
            "run by hand.",
            kind=CHOICE,
            default="auto",
            read=lambda c: _text(c.settings.database.get_integrity_check()),
            write=lambda c, v: c.settings.database.set_integrity_check(v),
            reset=lambda c: c.settings.database.reset_integrity_check(),
            options=_integrity_options,
            note="Applies the next time the database is opened.",
        ),
        Spec(
            id="database.integrity_check_interval_minutes",
            section="system",
            group="Database",
            label="Time between automatic checks",
            description="In Automatic mode, the database is checked at most this often.",
            kind=INTEGER,
            default=1440,
            read=lambda c: c.settings.database.get_integrity_check_interval_minutes(),
            write=lambda c, v: c.settings.database.set_integrity_check_interval_minutes(v),
            reset=lambda c: c.settings.database.reset_integrity_check_interval_minutes(),
            minimum=1,
            unit="minutes",
            advanced=True,
            note="Used in Automatic mode. Applies the next time the database is opened.",
        ),
    )


SECTIONS = ("general", "search", "indexing", "sources", "tiers", "results", "system", "addons")

# The order of the fixed settings within a section; ones that depend on what is installed follow.
_ORDER = (
    "languages.languages",
    "location.data",
    "location.backups",
    "updates.check",
    "updates.skipped_version",
    "updates.snoozed_until",
    "metrics.opt_in",
    "search.engine",
    "search.snippet_context_chars",
    "search.export_format",
    "index.workers",
    "index.retry_attempts",
    "ocr.engine",
    "ocr.gpu",
    "index.stability_check_seconds",
    "index.stale_lock",
    "sources.removed_retention_minutes",
    "tiers.default",
    "tiers.phases",
    "tiers.min_size_factor",
    "tiers.max_job_pages",
    "tiers.max_job_megabytes",
    "tiers.wait_timeout_minutes",
    "confidence.bands",
    "logs.level",
    "logs.retention_days",
    "database.integrity_check",
    "database.integrity_check_interval_minutes",
)


class SettingsService:
    """Lists, changes and resets the settings, on the core client `client()` returns.

    `release()` is called after a change that moved the core's data, so the next call builds a
    fresh client on the new location.
    """

    def __init__(
        self, client: Callable[[], Any], release: Callable[[], None] | None = None
    ) -> None:
        self._client = client
        self._release = release or (lambda: None)
        self._fixed = _specs()

    def sections(self) -> list[str]:
        return list(SECTIONS)

    def _specs_for(self, client: Any, section: str) -> list[Spec]:
        """The settings of a section: the fixed ones in order, then those that depend on what is
        installed."""
        rank = {key: index for index, key in enumerate(_ORDER)}
        fixed = [spec for spec in self._fixed if spec.section == section]
        fixed.sort(key=lambda spec: rank.get(spec.id, len(rank)))
        if section == "search":
            return [*fixed, *search_specs(client)]
        if section == "addons":
            return addon_specs(client)
        return fixed

    def list(self, section: str) -> list[dict[str, object]]:
        if section not in SECTIONS:
            raise SettingNotFoundError(f"There is no settings section {section!r}.")
        client = self._client()
        return [self._describe(client, spec) for spec in self._specs_for(client, section)]

    def changed(self) -> list[dict[str, object]]:
        """Every setting that is not at its default, for a support report (folders left out)."""
        rows = []
        for section in SECTIONS:
            for row in self.list(section):
                if (
                    row["type"] != PATH
                    and not row["is_default"]
                    and row["resettable"]
                    and not row["readonly"]
                ):
                    rows.append(row)
        return rows

    def update(
        self,
        section: str,
        setting_id: str,
        value: object,
        options: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        client = self._client()
        spec = self._spec(client, section, setting_id)
        self._refuse_if_locked(client, spec)
        if spec.write is None and spec.write_with is None:
            raise InvalidSettingError("This setting cannot be changed here.")
        value = self._check(client, spec, value)
        options = self._options(spec, options)
        return self._apply(
            client,
            spec,
            lambda: (
                spec.write_with(client, value, options)
                if spec.write_with
                else spec.write(client, value)
            ),  # type: ignore[misc]
        )

    def reset(
        self,
        section: str,
        setting_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        client = self._client()
        spec = self._spec(client, section, setting_id)
        self._refuse_if_locked(client, spec)
        if spec.reset is None and spec.reset_with is None:
            raise InvalidSettingError("This setting has nothing to reset to.")
        options = self._options(spec, options)
        return self._apply(
            client,
            spec,
            lambda: spec.reset_with(client, options) if spec.reset_with else spec.reset(client),  # type: ignore[misc]
        )

    def _apply(self, client: Any, spec: Spec, action: Callable[[], None]) -> dict[str, object]:
        # Imported here so the module loads without the core (tests of the pure parts).
        from vethuq.errors import InvalidSettingValueError, LanguageUnavailableError

        catches = (InvalidSettingValueError, LanguageUnavailableError, *spec.catches)
        if spec.moves:
            self._prepare_move(client)
        try:
            action()
        except catches as error:
            raise InvalidSettingError(str(error)) from error
        finally:
            if spec.moves:
                self._release()
        # After a move the client is new; describe on whichever the service now hands out.
        return self._describe(self._client() if spec.moves else client, spec)

    @staticmethod
    def _prepare_move(client: Any) -> None:
        """Moving the data needs no run in progress and no open database."""
        status = client.index.status()
        if status is not None and status.active:
            raise InvalidSettingError("Indexing is running. Stop it before moving the data folder.")
        client.close()

    @staticmethod
    def _options(spec: Spec, options: dict[str, Any] | None) -> dict[str, Any]:
        options = options or {}
        if set(options) - {"move"} or not isinstance(options.get("move", True), bool):
            raise InvalidSettingError("The only option is move: true or false.")
        if options and not spec.moves:
            raise InvalidSettingError("This setting takes no options.")
        return options

    @staticmethod
    def _refuse_if_locked(client: Any, spec: Spec) -> None:
        reason = spec.locked(client) if spec.locked else ""
        if reason:
            raise InvalidSettingError(reason)

    def _spec(self, client: Any, section: str, setting_id: str) -> Spec:
        if section in SECTIONS:
            for spec in self._specs_for(client, section):
                if spec.id == setting_id:
                    return spec
        raise SettingNotFoundError(f"There is no setting {setting_id!r} in {section!r}.")

    @staticmethod
    def _is_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    @staticmethod
    def _check(client: Any, spec: Spec, value: object) -> Any:
        """Refuse a value of the wrong kind or outside the offered ones, before the core sees it."""
        if spec.kind == BOOLEAN:
            if not isinstance(value, bool):
                raise InvalidSettingError("Use true or false.")
        elif spec.kind in (INTEGER, NUMBER):
            whole = SettingsService._is_int(value)
            number = whole or (isinstance(value, float))
            if not number or (spec.kind == INTEGER and not whole):
                raise InvalidSettingError(
                    "Use a whole number." if spec.kind == INTEGER else "Use a number."
                )
            if spec.minimum is not None and value < spec.minimum:  # type: ignore[operator]
                raise InvalidSettingError(f"Use {spec.minimum:g} or more.")
            if spec.maximum is not None and value > spec.maximum:  # type: ignore[operator]
                raise InvalidSettingError(f"Use {spec.maximum:g} or less.")
        elif spec.kind in (TEXT, PATH):
            if not isinstance(value, str) or not value.strip():
                raise InvalidSettingError("Enter a value.")
        elif spec.kind == CHOICE:
            SettingsService._check_choice(client, spec, value)
        elif spec.kind == MULTI:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise InvalidSettingError("Choose from the list.")
            if len(set(value)) != len(value):
                raise InvalidSettingError("Each choice can be made once.")
            if spec.minimum is not None and len(value) < spec.minimum:
                raise InvalidSettingError(f"Choose at least {spec.minimum:g}.")
            for item in value:
                SettingsService._check_choice(client, spec, item)
        elif spec.kind == BANDS:
            ok = (
                isinstance(value, list)
                and len(value) == 3
                and all(SettingsService._is_int(item) for item in value)
                and spec.minimum <= value[0] < value[1] < value[2] <= spec.maximum  # type: ignore[operator]
            )
            if not ok:
                raise InvalidSettingError(
                    "The bands must be whole percentages, rising, from 0 to 100."
                )
        return value

    @staticmethod
    def _check_choice(client: Any, spec: Spec, value: object) -> None:
        assert spec.options is not None  # noqa: S101  # a choice always lists its options
        chosen = [
            option
            for option in spec.options(client)
            if option["value"] == value and type(option["value"]) is type(value)
        ]
        if not chosen:
            raise InvalidSettingError("That is not one of the choices.")
        if chosen[0].get("available") is False:
            raise InvalidSettingError(str(chosen[0].get("reason") or "That is not available."))

    @staticmethod
    def _describe(client: Any, spec: Spec) -> dict[str, object]:
        value = spec.read(client)
        default = spec.default(client) if callable(spec.default) else spec.default
        locked = spec.locked(client) if spec.locked else ""
        if spec.kind == MULTI:
            is_default = sorted(value) == sorted(default)
        else:
            is_default = value == default and type(value) is type(default)
        item: dict[str, object] = {
            "id": spec.id,
            "section": spec.section,
            "label": spec.label,
            "description": spec.description,
            "type": spec.kind,
            "value": value,
            "default": default,
            "is_default": is_default,
            "advanced": spec.advanced,
            "note": spec.note(client) if callable(spec.note) else spec.note,
            "readonly": spec.write is None and spec.write_with is None,
            "locked": locked,
            "group": spec.group,
            "group_note": spec.group_note,
            "resettable": spec.resettable,
            "can_move": spec.moves,
        }
        if spec.options is not None:
            item["options"] = [
                {"available": True, "reason": "", **option} for option in spec.options(client)
            ]
        if spec.minimum is not None:
            item["min"] = spec.minimum
        if spec.maximum is not None:
            item["max"] = spec.maximum
        if spec.unit:
            item["unit"] = spec.unit
        if spec.labels:
            item["labels"] = list(spec.labels)
        return item
