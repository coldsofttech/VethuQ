"""The languages VethuQ can read documents in: `VethuQ().languages`.

Languages come from language add-ons; English (`vethuq-addon-english`) is installed with VethuQ.
A language is used only when it is **available** (its add-on is installed and, if licensed, its
licence is valid) and **enabled** (you haven't switched it off to save credits).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vethuq._db import _Database
from vethuq._languages import _LanguageCatalog, _Languages, _LanguageView

__all__ = ["Language", "Languages"]


@dataclass(frozen=True)
class Language:
    """A language VethuQ can read documents in."""

    id: str  # the language id used everywhere, e.g. "en"
    label: str  # "English"
    native_label: str  # the name in its own script, e.g. "తెలుగు"; empty if there is none
    script: str  # the writing system, e.g. "latin"
    default: bool  # the system default language
    installed: bool  # its add-on is installed
    available: bool  # installed and usable now (for instance its licence is valid)
    enabled: bool  # not switched off by the user
    reason: str  # why it isn't available, when it isn't

    @property
    def usable(self) -> bool:
        """Available and enabled: the languages that are actually used."""
        return self.available and self.enabled

    @classmethod
    def _from_view(cls, view: _LanguageView) -> Language:
        return cls(
            id=view.id,
            label=view.label,
            native_label=view.native_label,
            script=view.script,
            default=view.default,
            installed=view.installed,
            available=view.available,
            enabled=view.enabled,
            reason="" if view.available else view.reason,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "native_label": self.native_label,
            "script": self.script,
            "default": self.default,
            "installed": self.installed,
            "available": self.available,
            "enabled": self.enabled,
            "reason": self.reason,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Languages:
    """The languages VethuQ can read documents in.

    Not created directly: use `VethuQ().languages`.
    """

    def __init__(self, database: _Database, catalog: _LanguageCatalog) -> None:
        self._database = database
        self._catalog = catalog

    def list_all(self) -> list[Language]:
        """Every language VethuQ knows, the system default (English) first, then by id.

        Includes languages a source still refers to whose add-on is no longer installed
        (`installed=False`).
        """
        with self._database.session() as session:
            views = _Languages.views(session, self._catalog.specs())
        return [Language._from_view(view) for view in views]

    def list_enabled(self) -> list[Language]:
        """The languages that are used: available and enabled."""
        return [language for language in self.list_all() if language.usable]

    def get(self, language_id: str) -> Language | None:
        """One language by id, or None if VethuQ doesn't know it."""
        with self._database.session() as session:
            view = _Languages.find(session, self._catalog.specs(), language_id)
        return Language._from_view(view) if view is not None else None

    def default(self) -> Language:
        """The system default language: English. It is the fallback when nothing else is usable.

        Raises `LanguageUnavailableError` if no installed add-on provides one.
        """
        spec = _Languages.default(self._catalog.specs())
        language = self.get(spec.id)
        assert language is not None  # noqa: S101 - the default spec is always known
        return language

    def enable(self, language_id: str) -> Language:
        """Switch a language back on and return it. It must be available.

        Raises `LanguageUnavailableError` if it is unknown or not available.
        """
        with self._database.session() as session:
            view = _Languages.enable(session, self._catalog.specs(), language_id)
        return Language._from_view(view)

    def disable(self, language_id: str) -> Language:
        """Switch a language off, so nothing uses it (and no credits are spent on it), and
        return it. It is also dropped from the default languages setting.

        At least one language must stay in use: disabling the last raises `LastLanguageError`.
        Raises `LanguageUnavailableError` if the language is unknown.
        """
        with self._database.session() as session:
            view = _Languages.disable(session, self._catalog.specs(), language_id)
        return Language._from_view(view)
