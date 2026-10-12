"""The settings the interface shows: what each is, how it is edited and how it is saved.

The core keeps the values (`client.settings.<area>`); this module adds what the core does not say:
a label, a description, the kind of control, and the allowed values. Settings are grouped into
sections, one section per page of the settings screen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

BOOLEAN, INTEGER, NUMBER, CHOICE = "boolean", "integer", "number", "choice"
MULTI, BANDS = "multichoice", "bands"

_NEXT_RUN = "Applies from the next indexing run."


class SettingNotFoundError(LookupError):
    """No such section or setting."""


class InvalidSettingError(ValueError):
    """The value is not allowed for the setting (the message says why)."""


@dataclass(frozen=True)
class Spec:
    """One setting. `read`, `write` and `reset` talk to the core client."""

    id: str
    section: str
    label: str
    description: str
    kind: str
    default: Any  # the value, or a function of the client when it depends on the installation
    read: Callable[[Any], Any]
    write: Callable[[Any, Any], None]
    reset: Callable[[Any], None]
    options: Callable[[Any], list[dict[str, object]]] | None = None
    labels: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    advanced: bool = False
    note: str = ""


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
            id="languages.languages",
            section="general",
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
            id="metrics.opt_in",
            section="general",
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
    )


class SettingsService:
    """Lists, changes and resets the settings, on the core client `client()` returns."""

    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client
        self._specs = _specs()

    def sections(self) -> list[str]:
        return list(dict.fromkeys(spec.section for spec in self._specs))

    def list(self, section: str) -> list[dict[str, object]]:
        specs = [spec for spec in self._specs if spec.section == section]
        if not specs:
            raise SettingNotFoundError(f"There is no settings section {section!r}.")
        client = self._client()
        return [self._describe(client, spec) for spec in specs]

    def update(self, section: str, setting_id: str, value: object) -> dict[str, object]:
        spec = self._spec(section, setting_id)
        client = self._client()
        value = self._check(client, spec, value)
        # Imported here so the module loads without the core (tests of the pure parts).
        from vethuq.errors import InvalidSettingValueError, LanguageUnavailableError

        try:
            spec.write(client, value)
        except (InvalidSettingValueError, LanguageUnavailableError) as error:
            raise InvalidSettingError(str(error)) from error
        return self._describe(client, spec)

    def reset(self, section: str, setting_id: str) -> dict[str, object]:
        spec = self._spec(section, setting_id)
        client = self._client()
        spec.reset(client)
        return self._describe(client, spec)

    def _spec(self, section: str, setting_id: str) -> Spec:
        for spec in self._specs:
            if spec.section == section and spec.id == setting_id:
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
            "note": spec.note,
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
