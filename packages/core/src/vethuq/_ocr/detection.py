"""Telling which language a scanned file is in, from how well each language reads it.

A language that does not match a page reads it badly: its recognizer makes up characters for
glyphs it does not know, with low confidence. So a file is read in its first candidate language
and the result is judged by its confidence and by whether the characters it produced are in that
language's script (`LanguageSpec.script_ranges`). Confident: that is the language. Unsure: the
other candidates read it too, and lines that no language read believably are left out of the
searchable text. A file with a text layer shows its language by the scripts in its text.

The thresholds are provisional, set from how the recognizers behave on typical pages rather than
tuned on a corpus of real scans, and are class constants so they can be adjusted in one place.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from vethuq_addon_api import LanguageSpec


@dataclass(frozen=True)
class _Assessment:
    """How well one language read a file's scanned pages."""

    verdict: str
    confidence: float | None = None
    script_share: float | None = None
    letters: int = 0


class _Scripts:
    """Which language's writing system a character belongs to, by `script_ranges`."""

    @staticmethod
    def in_ranges(char: str, ranges: Iterable[tuple[int, int]]) -> bool:
        code = ord(char)
        return any(first <= code <= last for first, last in ranges)

    @staticmethod
    def letters(text: str) -> list[str]:
        """The letters of `text`, with the marks that belong to them (the vowel signs of Telugu
        and other Indic scripts are marks, not letters, but part of the writing all the same)."""
        return [char for char in text if unicodedata.category(char)[0] in ("L", "M")]

    @staticmethod
    def own_share(text: str, language: LanguageSpec) -> tuple[int, int]:
        """(letters in `text`, how many of them are in `language`'s script). A language with no
        script ranges has no script to check: all of its letters count as its own."""
        letters = _Scripts.letters(text)
        if not language.script_ranges:
            return len(letters), len(letters)
        own = sum(1 for char in letters if _Scripts.in_ranges(char, language.script_ranges))
        return len(letters), own

    @staticmethod
    def present(text: str, languages: Sequence[LanguageSpec]) -> list[str]:
        """The ids of the `languages` whose script `text` contains, in the order given. A
        language with no script ranges is never recognised by its text."""
        letters = _Scripts.letters(text)
        return [
            language.id
            for language in languages
            if language.script_ranges
            and any(_Scripts.in_ranges(char, language.script_ranges) for char in letters)
        ]


class _LanguageDetector:
    # The verdicts. NATIVE: no page needed OCR (the text came from the file). EMPTY: too little
    # text was found to judge (a photo, a blank page), so the first language stands.
    NATIVE = "native"
    EMPTY = "empty"
    CONFIDENT = "confident"
    UNSURE = "unsure"

    # Fewer letters than this across the scanned pages is not enough to judge.
    MIN_LETTERS = 12
    # A language is accepted when it reads the scanned pages at least this confidently (mean
    # confidence, weighted by how much text each page has)...
    MIN_CONFIDENCE = 0.80
    # ...and at least this share of what it read is in its own script.
    MIN_SCRIPT_SHARE = 0.60
    # A line from a language that is being doubted (or from a later pass) is kept only if the
    # recognizer was at least this sure of it, and it is mostly in the language's script...
    MIN_LINE_CONFIDENCE = 0.60
    MIN_LINE_SCRIPT_SHARE = 0.50
    # ...except a line with no letters at all (numbers, punctuation), which has no script to
    # check and so has to be read very confidently.
    MIN_LETTERLESS_LINE_CONFIDENCE = 0.85

    @staticmethod
    def assess(pages: Iterable[tuple[bool, str, float]], language: LanguageSpec) -> _Assessment:
        """Judge how well `language` read the scanned pages. `pages` are (scanned, text,
        confidence); a page that was not scanned says nothing about the recognizer."""
        letters = own = 0
        weighted = 0.0
        scanned = False
        for was_scanned, text, confidence in pages:
            if not was_scanned:
                continue
            scanned = True
            count, mine = _Scripts.own_share(text, language)
            letters += count
            own += mine
            weighted += confidence * count
        if not scanned:
            return _Assessment(_LanguageDetector.NATIVE)
        if letters < _LanguageDetector.MIN_LETTERS:
            return _Assessment(_LanguageDetector.EMPTY, letters=letters)
        confidence = weighted / letters
        share = own / letters
        confident = (
            confidence >= _LanguageDetector.MIN_CONFIDENCE
            and share >= _LanguageDetector.MIN_SCRIPT_SHARE
        )
        return _Assessment(
            _LanguageDetector.CONFIDENT if confident else _LanguageDetector.UNSURE,
            confidence=confidence,
            script_share=share,
            letters=letters,
        )

    @staticmethod
    def keep_line(text: str, confidence: float, language: LanguageSpec) -> bool:
        """Whether a line `language` read is believable enough to keep in a page's text."""
        total, own = _Scripts.own_share(text, language)
        if total == 0:
            return confidence >= _LanguageDetector.MIN_LETTERLESS_LINE_CONFIDENCE
        return (
            confidence >= _LanguageDetector.MIN_LINE_CONFIDENCE
            and own / total >= _LanguageDetector.MIN_LINE_SCRIPT_SHARE
        )

    @staticmethod
    def believable(
        lines: Iterable[tuple[str, float]], language: LanguageSpec
    ) -> list[tuple[str, float]]:
        return [
            (text, score)
            for text, score in lines
            if text.strip() and _LanguageDetector.keep_line(text, score, language)
        ]
