"""The case normalizer: `ignore` treats upper and lower case as the same letter."""

from __future__ import annotations

from vethuq_core.search.normalizers.base import Folded


class CaseNormalizer:
    """Lower-cases text, one character for one character (so positions never move)."""

    name = "case"
    levels = ("match", "ignore")
    identity = "match"

    def fold(self, text: str, level: str) -> Folded:
        if level == self.identity:
            return Folded(text)
        lowered = text.lower()
        if len(lowered) == len(text):
            return Folded(lowered)
        # A character whose lower case is longer than itself ('İ'): keep its first character.
        return Folded("".join(char.lower()[:1] for char in text))

    def char_table(self, level: str) -> dict[int, str] | None:
        return None
