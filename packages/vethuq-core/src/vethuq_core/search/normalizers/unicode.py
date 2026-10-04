"""The Unicode normalizer: `basic` composes text (NFC), `full` also folds compatibility forms
and accents (`ﬁ` is `fi`, a full-width `Ａ` is `A`, `é` is `e`)."""

from __future__ import annotations

import unicodedata

from vethuq_core.search.normalizers.base import Folded


class UnicodeNormalizer:
    """Normalizes the characters of a text, keeping track of where each came from.

    The text is cut before each space (nothing composes across one) and, inside a word, before
    each character that starts a new base (so `é` written as `e` plus an accent is one unit);
    each unit is normalized by itself, so the positions of the result can be traced back to
    the original, and a unit that doesn't normalize the same piece by piece (Hangul jamo,
    say) is traced back as a whole.
    """

    name = "unicode"
    levels = ("off", "basic", "full")
    identity = "off"

    def fold(self, text: str, level: str) -> Folded:
        if level == self.identity or UnicodeNormalizer._is_settled(text, level):
            return Folded(text)
        pieces: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        for first, last in UnicodeNormalizer._segments(text):
            segment = text[first:last]
            whole = UnicodeNormalizer._normalize(segment, level)
            parts = [
                (a, b, UnicodeNormalizer._normalize(text[a:b], level))
                for a, b in UnicodeNormalizer._units(text, first, last)
            ]
            if "".join(part for _, _, part in parts) == whole:
                for a, b, part in parts:
                    pieces.append(part)
                    starts.extend([a] * len(part))
                    ends.extend([b] * len(part))
            else:
                pieces.append(whole)
                starts.extend([first] * len(whole))
                ends.extend([last] * len(whole))
        return Folded("".join(pieces), starts, ends)

    def char_table(self, level: str) -> dict[int, str] | None:
        return None

    def index_form(self, text: str) -> str:
        return self.fold(text, "full").text

    @staticmethod
    def _normalize(text: str, level: str) -> str:
        if level == "basic":
            return unicodedata.normalize("NFC", text)
        decomposed = unicodedata.normalize("NFKD", text)
        return unicodedata.normalize(
            "NFC", "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
        )

    @staticmethod
    def _is_settled(text: str, level: str) -> bool:
        """Whether normalizing `text` would change nothing."""
        if level == "basic":
            return unicodedata.is_normalized("NFC", text)
        return text.isascii() or UnicodeNormalizer._normalize(text, level) == text

    @staticmethod
    def _segments(text: str) -> list[tuple[int, int]]:
        """`text` cut before each whitespace character."""
        cuts = [0] + [i for i, char in enumerate(text) if char.isspace() and i > 0] + [len(text)]
        return [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if b > a]

    @staticmethod
    def _units(text: str, first: int, last: int) -> list[tuple[int, int]]:
        """`text[first:last]` cut before each character that isn't a combining mark."""
        cuts = (
            [first]
            + [i for i in range(first + 1, last) if unicodedata.combining(text[i]) == 0]
            + [last]
        )
        return list(zip(cuts, cuts[1:], strict=False))
