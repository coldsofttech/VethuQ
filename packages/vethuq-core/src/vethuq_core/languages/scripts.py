"""Writing systems, found by the Unicode block a character sits in.

A `Script` is data: its code point ranges and how its combining marks must be treated. Adding a
script means adding one entry to `Scripts.REGISTRY`; nothing that asks "which scripts are in this
text" changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Script:
    """One writing system.

    `ranges` are inclusive `(first, last)` code points. `strips_marks` says whether the Unicode
    `full` normalization may drop this script's combining marks (the accents of `é` are not part
    of the letter), which is not true of scripts whose vowel signs and virama are part of the
    syllable - dropping them changes the word.
    """

    id: str
    ranges: tuple[tuple[int, int], ...]
    strips_marks: bool

    def pattern(self) -> re.Pattern[str]:
        body = "".join(f"{chr(first)}-{chr(last)}" for first, last in self.ranges)
        return re.compile(f"[{body}]")


class Scripts:
    LATIN = "latin"
    TELUGU = "telugu"

    REGISTRY: dict[str, Script] = {
        LATIN: Script(
            LATIN,
            # Basic Latin letters, Latin-1 Supplement to Latin Extended-B, and Extended Additional.
            ranges=((0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F), (0x1E00, 0x1EFF)),
            strips_marks=True,
        ),
        TELUGU: Script(TELUGU, ranges=((0x0C00, 0x0C7F),), strips_marks=False),
    }

    _patterns: dict[str, re.Pattern[str]] = {}

    @staticmethod
    def get(script_id: str) -> Script | None:
        return Scripts.REGISTRY.get(script_id)

    @staticmethod
    def _pattern(script_id: str) -> re.Pattern[str]:
        pattern = Scripts._patterns.get(script_id)
        if pattern is None:
            pattern = Scripts._patterns[script_id] = Scripts.REGISTRY[script_id].pattern()
        return pattern

    @staticmethod
    def contains(text: str, script_id: str) -> bool:
        """Whether `text` has at least one character of the script (False for an unknown one)."""
        if script_id not in Scripts.REGISTRY:
            return False
        return Scripts._pattern(script_id).search(text) is not None

    @staticmethod
    def counts(text: str) -> dict[str, int]:
        """How many characters of each known script `text` has; scripts with none are left out."""
        found = {}
        for script_id in Scripts.REGISTRY:
            count = len(Scripts._pattern(script_id).findall(text))
            if count:
                found[script_id] = count
        return found

    @staticmethod
    def present(text: str) -> frozenset[str]:
        """The ids of the known scripts `text` contains."""
        return frozenset(Scripts.counts(text))

    @staticmethod
    def dominant(text: str) -> str | None:
        """The script with the most characters in `text` (first registered wins a tie), or None."""
        counts = Scripts.counts(text)
        if not counts:
            return None
        return max(counts, key=lambda script_id: counts[script_id])

    @staticmethod
    def strips_marks(char: str) -> bool:
        """Whether a combining mark following `char` may be folded away by Unicode `full`.

        True for every character outside a known non-stripping script, so text in scripts this
        registry doesn't know keeps behaving exactly as it did before scripts existed.
        """
        code = ord(char)
        for script in Scripts.REGISTRY.values():
            if not script.strips_marks and any(a <= code <= b for a, b in script.ranges):
                return False
        return True
