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
    default: Any
    read: Callable[[Any], Any]
    write: Callable[[Any, Any], None]
    reset: Callable[[Any], None]
    options: Callable[[Any], list[dict[str, object]]] | None = None
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
    )


class SettingsService:
    """Lists, changes and resets the settings, on the core client `client()` returns."""

    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client
        self._specs = _specs()

    def sections(self) -> list[str]:
        return sorted({spec.section for spec in self._specs})

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
        from vethuq.errors import InvalidSettingValueError

        try:
            spec.write(client, value)
        except InvalidSettingValueError as error:
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
    def _check(client: Any, spec: Spec, value: object) -> Any:
        """Refuse a value of the wrong kind or outside the offered ones, before the core sees it."""
        if spec.kind == BOOLEAN:
            if not isinstance(value, bool):
                raise InvalidSettingError("Use true or false.")
        elif spec.kind in (INTEGER, NUMBER):
            number = isinstance(value, int | float) and not isinstance(value, bool)
            if not number or (spec.kind == INTEGER and not isinstance(value, int)):
                raise InvalidSettingError(
                    "Use a whole number." if spec.kind == INTEGER else "Use a number."
                )
            if spec.minimum is not None and value < spec.minimum:
                raise InvalidSettingError(f"Use {spec.minimum:g} or more.")
            if spec.maximum is not None and value > spec.maximum:
                raise InvalidSettingError(f"Use {spec.maximum:g} or less.")
        elif spec.kind == CHOICE:
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
        return value

    @staticmethod
    def _describe(client: Any, spec: Spec) -> dict[str, object]:
        value = spec.read(client)
        item: dict[str, object] = {
            "id": spec.id,
            "section": spec.section,
            "label": spec.label,
            "description": spec.description,
            "type": spec.kind,
            "value": value,
            "default": spec.default,
            "is_default": value == spec.default and type(value) is type(spec.default),
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
        return item
