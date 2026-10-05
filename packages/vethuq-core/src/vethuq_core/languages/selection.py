"""Which languages OCR reads a file in: parsing what the user asked for, and what it resolves to.

A selection is a list of language ids (`en`, `te`) or `auto` (every enabled language). It can come
from a command-line flag, from a source, or from the global setting, in that order of precedence;
`LanguageSelection.resolve` turns it into the ordered candidates OCR works through. One candidate
is read directly; several are told apart by detection (see `vethuq_core.ocr.detection`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from vethuq_core.errors import LanguageUnavailableError


class UnknownLanguageError(ValueError):
    """A language id that no manifest declares."""


def _catalog():
    # Imported on use: the ocr package imports this module.
    from vethuq_core.ocr.catalog import OcrCatalog

    return OcrCatalog


@dataclass(frozen=True)
class Candidates:
    """The languages a file may be read in, in the order they are tried (the default language
    first, then the rest in catalog order).

    `explicit` says the user chose them (a flag or a source), as opposed to the global setting.
    """

    ids: tuple[str, ...]
    explicit: bool = False

    @property
    def first(self) -> str:
        return self.ids[0]

    @property
    def rest(self) -> tuple[str, ...]:
        return self.ids[1:]

    @property
    def needs_detection(self) -> bool:
        """More than one candidate: which of them the file is in has to be worked out."""
        return len(self.ids) > 1

    @property
    def choice_source(self) -> str:
        """How a single candidate came to be used: `manual` if the user chose it, else `default`."""
        return "manual" if self.explicit else "default"


class LanguageSelection:
    AUTO = "auto"
    SEPARATOR = ","

    @staticmethod
    def parse(value: str | Iterable[str] | None) -> list[str] | None:
        """The language ids `value` names, in catalog order with duplicates removed; `["auto"]`
        for `auto`; None for no value (nothing chosen).

        Accepts `"en,te"`, `"en, te"` or a list of those. Raises `UnknownLanguageError` for an id
        no manifest declares - not for one that merely isn't installed, which is
        `LanguageSelection.resolve`'s concern.
        """
        if value is None:
            return None
        parts = [value] if isinstance(value, str) else list(value)
        wanted = [
            piece.strip().lower()
            for part in parts
            for piece in part.split(LanguageSelection.SEPARATOR)
            if piece.strip()
        ]
        if not wanted:
            return None
        if LanguageSelection.AUTO in wanted:
            return [LanguageSelection.AUTO]
        known = [lang.id for lang in _catalog().languages()]
        for language_id in wanted:
            if language_id not in known:
                raise UnknownLanguageError(
                    f"Unknown language '{language_id}'. Known languages: {', '.join(known)}."
                )
        return [language_id for language_id in known if language_id in wanted]

    @staticmethod
    def format(ids: Iterable[str]) -> str:
        return LanguageSelection.SEPARATOR.join(ids)

    @staticmethod
    def resolve(requested: list[str] | None, *, explicit: bool, enabled: list[str]) -> Candidates:
        """The candidates for `requested` (parsed ids, or None for the default language alone).

        `enabled` are the language ids OCR can use now (default first). `auto` means all of them.
        Raises `LanguageUnavailableError` if a requested language isn't one of them.
        """
        if requested is None:
            requested = [enabled[0]]
        elif requested == [LanguageSelection.AUTO]:
            requested = list(enabled)
        missing = [language_id for language_id in requested if language_id not in enabled]
        if missing:
            language = _catalog().language(missing[0])
            label = language.label if language is not None else missing[0]
            hint = (
                f"Install it with: {language.install_hint}, or re-run the installer."
                if language is not None
                else None
            )
            raise LanguageUnavailableError(
                f"The {label} OCR language is not installed or enabled.", hint
            )
        return Candidates(ids=tuple(requested), explicit=explicit)
