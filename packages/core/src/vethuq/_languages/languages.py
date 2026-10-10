"""The language service: which languages exist, which can be used, and which the user has on.

Languages come from language add-ons (see `Addon.languages()`). A language is *available* when its
add-on is installed and says it can be used (for instance its licence is valid), and *enabled*
unless the user switched it off to save credits. Only a language that is both is used. At least one
usable language is always kept on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from vethuq._db import _Language
from vethuq._errors import _InvalidSettingValueError, _LanguageUnavailableError, _LastLanguageError
from vethuq._settings import _LanguageSettings
from vethuq_addon_api import LanguageSpec

_logger = logging.getLogger("vethuq.database")


@dataclass(frozen=True)
class _LanguageView:
    id: str
    label: str
    native_label: str
    script: str
    default: bool
    installed: bool
    available: bool
    enabled: bool
    reason: str

    @property
    def usable(self) -> bool:
        return self.available and self.enabled


class _LanguageCatalog:
    """Where the languages come from: a function returning the specs of the loaded add-ons."""

    def __init__(self, specs: Callable[[], list[LanguageSpec]]) -> None:
        self.specs = specs


class _Languages:
    @staticmethod
    def clean(ids: object) -> list[str]:
        """Language ids trimmed and lower-cased, blanks and repeats dropped, order kept."""
        if isinstance(ids, str) or ids is None:
            raise TypeError('languages must be a list of language ids, e.g. ["en", "te"]')
        cleaned: list[str] = []
        for item in ids:  # type: ignore[attr-defined]
            value = str(item).strip().lower()
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    @staticmethod
    def ensure_rows(session: Session, specs: list[LanguageSpec]) -> None:
        """Make sure every available language has its `languages` row, in the order of the specs
        (so the system default has the lowest id)."""
        known = set(session.scalars(select(_Language.language)))
        session.add_all(
            _Language(language=spec.id) for spec in specs if spec.available and spec.id not in known
        )
        session.flush()

    @staticmethod
    def views(session: Session, specs: list[LanguageSpec]) -> list[_LanguageView]:
        """Every language VethuQ knows: the ones add-ons provide, plus any a source still refers
        to whose add-on is gone. The system default first, then by id."""
        by_id = {spec.id: spec for spec in specs}
        disabled = set(_LanguageSettings.get_disabled(session))
        remembered = [code for code in session.scalars(select(_Language.language))]
        views = []
        for code in dict.fromkeys([*by_id, *remembered]):
            spec = by_id.get(code)
            views.append(
                _LanguageView(
                    id=code,
                    label=spec.label if spec else code,
                    native_label=spec.native_label if spec else "",
                    script=spec.script if spec else "",
                    default=bool(spec and spec.default),
                    installed=spec is not None,
                    available=bool(spec and spec.available),
                    enabled=code not in disabled,
                    reason=(spec.reason if spec else "its add-on isn't installed"),
                )
            )
        return sorted(views, key=lambda v: (not v.default, v.id))

    @staticmethod
    def find(session: Session, specs: list[LanguageSpec], code: str) -> _LanguageView | None:
        code = str(code).strip().lower()
        return next((v for v in _Languages.views(session, specs) if v.id == code), None)

    @staticmethod
    def default(specs: list[LanguageSpec]) -> LanguageSpec:
        """The system default language (English). Raises if no installed add-on provides one."""
        for spec in specs:
            if spec.default:
                return spec
        raise _LanguageUnavailableError(
            "No default language is installed.", "Install the English add-on: vethuq-addon-english."
        )

    @staticmethod
    def usable_ids(session: Session, specs: list[LanguageSpec]) -> list[str]:
        return [v.id for v in _Languages.views(session, specs) if v.usable]

    # ----- on and off -----------------------------------------------------------------------

    @staticmethod
    def disable(session: Session, specs: list[LanguageSpec], code: str) -> _LanguageView:
        """Switch a language off. Refuses the last usable one. Takes it out of the default
        languages, too."""
        view = _Languages._require(session, specs, code)
        if view.usable and _Languages.usable_ids(session, specs) == [view.id]:
            raise _LastLanguageError(
                f"{view.label} is the only language in use, so it can't be disabled.",
                "Enable another language first.",
            )
        disabled = _LanguageSettings.get_disabled(session)
        if view.id not in disabled:
            _LanguageSettings.set_disabled(session, [*disabled, view.id])
        chosen = _LanguageSettings.get_default(session)
        if view.id in chosen:
            _LanguageSettings.set_default(session, [c for c in chosen if c != view.id])
        _logger.info("Language disabled: %s", view.id)
        return _Languages._require(session, specs, view.id)

    @staticmethod
    def enable(session: Session, specs: list[LanguageSpec], code: str) -> _LanguageView:
        """Switch a language back on. It must be available."""
        view = _Languages._require(session, specs, code)
        if not view.available:
            raise _Languages._unavailable(view)
        disabled = _LanguageSettings.get_disabled(session)
        if view.id in disabled:
            _LanguageSettings.set_disabled(session, [c for c in disabled if c != view.id])
            _logger.info("Language enabled: %s", view.id)
        return _Languages._require(session, specs, view.id)

    @staticmethod
    def _require(session: Session, specs: list[LanguageSpec], code: str) -> _LanguageView:
        view = _Languages.find(session, specs, code)
        if view is None:
            raise _Languages._unknown([str(code)], session, specs)
        return view

    # ----- the default languages ------------------------------------------------------------

    @staticmethod
    def default_ids(session: Session, specs: list[LanguageSpec]) -> list[str]:
        """The languages a source with none of its own is read in: those saved, that are still
        usable; the system default if none are (or none were saved)."""
        usable = set(_Languages.usable_ids(session, specs))
        chosen = [c for c in _LanguageSettings.get_default(session) if c in usable]
        if chosen:
            return chosen
        system = _Languages.default(specs).id
        if system not in usable:
            _logger.warning("The default language %s is switched off; using it anyway", system)
        return [system]

    @staticmethod
    def set_default_ids(session: Session, specs: list[LanguageSpec], ids: object) -> list[str]:
        codes = _Languages.clean(ids)
        if not codes:
            raise _InvalidSettingValueError(
                "Choose at least one language.", "Use reset_languages() for the system default."
            )
        _Languages.validate(session, specs, codes)
        _LanguageSettings.set_default(session, codes)
        return codes

    # ----- checking what a caller asked for -------------------------------------------------

    @staticmethod
    def validate(session: Session, specs: list[LanguageSpec], codes: list[str]) -> list[_Language]:
        """The `languages` rows for `codes`, in language order, if every one can be used.

        Raises `LanguageUnavailableError` for an unknown language, one whose add-on is missing or
        unavailable, or one the user switched off.
        """
        _Languages.ensure_rows(session, specs)
        views = {v.id: v for v in _Languages.views(session, specs)}
        unknown = [c for c in codes if c not in views]
        if unknown:
            raise _Languages._unknown(unknown, session, specs)
        for code in codes:
            view = views[code]
            if not view.available or not view.enabled:
                raise _Languages._unavailable(view)
        return list(
            session.scalars(
                select(_Language).where(_Language.language.in_(codes)).order_by(_Language.id)
            )
        )

    @staticmethod
    def _unknown(codes: list[str], session: Session, specs: list[LanguageSpec]):
        names = ", ".join(f"'{code}'" for code in codes)
        noun = "language" if len(codes) == 1 else "languages"
        usable = _Languages.usable_ids(session, specs)
        return _LanguageUnavailableError(
            f"Unknown {noun} {names}.", f"Available languages: {', '.join(usable) or 'none'}."
        )

    @staticmethod
    def _unavailable(view: _LanguageView):
        if not view.available:
            why = view.reason or "it isn't available"
            return _LanguageUnavailableError(
                f"The {view.label} language can't be used: {why}.",
                "Install or renew its add-on, then try again.",
            )
        return _LanguageUnavailableError(
            f"The {view.label} language is disabled.",
            f"Enable it with languages.enable('{view.id}').",
        )
