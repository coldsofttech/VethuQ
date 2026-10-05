"""The OCR languages this install can use, and which one a piece of text calls for."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vethuq_core.languages.scripts import Scripts

if TYPE_CHECKING:  # the ocr package imports this one, so the catalog is loaded on use
    from vethuq_core.ocr.catalog import OcrComponentInfo


def _catalog():
    from vethuq_core.ocr.catalog import OcrCatalog

    return OcrCatalog


class Languages:
    @staticmethod
    def default() -> OcrComponentInfo:
        """English - what an install with no other choice recognizes."""
        return _catalog().default_language()

    @staticmethod
    def enabled() -> list[OcrComponentInfo]:
        """Languages OCR can use, default first."""
        return _catalog().enabled_languages()

    @staticmethod
    def enabled_ids() -> list[str]:
        return [lang.id for lang in Languages.enabled()]

    @staticmethod
    def get(language_id: str) -> OcrComponentInfo | None:
        return _catalog().language(language_id)

    @staticmethod
    def for_text(text: str) -> list[OcrComponentInfo]:
        """The enabled languages whose script `text` contains, in catalog order.

        Text with no character of any known script (digits and punctuation only) yields an
        empty list, which callers read as "nothing language-specific to do".
        """
        present = Scripts.present(text)
        return [lang for lang in Languages.enabled() if lang.script in present]

    @staticmethod
    def is_default_only(text: str) -> bool:
        """Whether `text` needs nothing but the default (English) handling: it has no character
        of a script other than the default language's."""
        others = Scripts.present(text) - {Languages.default().script}
        return not others
