"""Choosing OCR languages in the desktop app: the logic the windows share (no Tk here).

The choice is only offered when more than one language is enabled; with English alone there is
nothing to choose and every window behaves as it always has.
"""

from __future__ import annotations

from vethuq_core.languages import Languages

AUTO = "auto"


class LanguageChoice:
    @staticmethod
    def available() -> bool:
        """Whether there is a choice to make (another language is enabled besides English)."""
        return len(Languages.enabled()) > 1

    @staticmethod
    def label(language_id: str) -> str:
        info = Languages.get(language_id)
        return info.display_label if info else language_id

    @staticmethod
    def selection_ids(value: str | None) -> list[str]:
        """The language ids in a stored value (`en,te`); empty for `auto` or nothing."""
        if not value or value.strip().lower() == AUTO:
            return []
        return [part.strip() for part in value.split(",") if part.strip()]

    @staticmethod
    def stored(automatic: bool, chosen: list[str]) -> str:
        """The value to store: `auto`, or the chosen ids in catalog order (`en,te`)."""
        if automatic or not chosen:
            return AUTO
        order = Languages.enabled_ids()
        return ",".join(sorted(set(chosen), key=lambda i: order.index(i) if i in order else 99))
