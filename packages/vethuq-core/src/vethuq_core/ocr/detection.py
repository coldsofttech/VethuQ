"""Telling which language a scanned file is in, from how well each language reads it.

A language that does not match a page reads it badly: its recognizer makes up characters for
glyphs it does not know, with low confidence. So the file is read in the first candidate language,
and the result is judged by its confidence and by whether the characters it produced are in that
language's script. Confident: that is the language. Unsure: the other candidates read it too (see
`vethuq_core.ocr.plan`), and lines that no language read well are left out of the searchable text.

The thresholds below are provisional - set from how the recognizers behave on typical pages, not
tuned on a corpus of real Telugu and English scans - and are class constants so they can be
adjusted in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from vethuq_core.languages import Scripts
from vethuq_core.ocr.catalog import OcrComponentInfo
from vethuq_core.readers import PageResult


@dataclass(frozen=True)
class Assessment:
    """How well one language read a file's scanned pages."""

    verdict: str
    confidence: float | None = None
    script_share: float | None = None
    letters: int = 0


class LanguageDetector:
    # The verdicts. NATIVE: no page needed OCR (the text came from the file). EMPTY: too little
    # text was found to judge - a photo, a blank page - so the first language stands.
    NATIVE = "native"
    EMPTY = "empty"
    CONFIDENT = "confident"
    UNSURE = "unsure"

    # Fewer characters than this across the scanned pages is not enough to judge.
    MIN_LETTERS = 12
    # A language is accepted when it reads the scanned pages at least this confidently (mean
    # confidence, weighted by how much text each page has)...
    MIN_CONFIDENCE = 0.80
    # ...and at least this share of what it read is in its own script.
    MIN_SCRIPT_SHARE = 0.60
    # A line from a language pass that is being doubted (or from a later one) is kept only if the
    # recognizer was at least this sure of it, and mostly in the language's script...
    MIN_LINE_CONFIDENCE = 0.60
    MIN_LINE_SCRIPT_SHARE = 0.50
    # ...except a line with no letters at all (numbers, punctuation), which has no script to
    # check and so has to be read very confidently.
    MIN_LETTERLESS_LINE_CONFIDENCE = 0.85

    @staticmethod
    def assess(pages: list[PageResult], language: OcrComponentInfo) -> Assessment:
        """Judge how well `language` read the scanned (OCR'd) `pages`."""
        scanned = [page for page in pages if page.source == "ocr"]
        if not scanned:
            return Assessment(LanguageDetector.NATIVE)
        letters = 0
        own = 0
        weighted = 0.0
        for page in scanned:
            counts = Scripts.counts(page.text)
            count = sum(counts.values())
            letters += count
            own += counts.get(language.script, 0)
            weighted += page.confidence * count
        if letters < LanguageDetector.MIN_LETTERS:
            return Assessment(LanguageDetector.EMPTY, letters=letters)
        confidence = weighted / letters
        share = own / letters
        confident = (
            confidence >= LanguageDetector.MIN_CONFIDENCE
            and share >= LanguageDetector.MIN_SCRIPT_SHARE
        )
        return Assessment(
            LanguageDetector.CONFIDENT if confident else LanguageDetector.UNSURE,
            confidence=confidence,
            script_share=share,
            letters=letters,
        )

    @staticmethod
    def keep_line(text: str, confidence: float, language: OcrComponentInfo) -> bool:
        """Whether a line `language` read is believable enough to keep in a page's text."""
        counts = Scripts.counts(text)
        total = sum(counts.values())
        if total == 0:
            return confidence >= LanguageDetector.MIN_LETTERLESS_LINE_CONFIDENCE
        return (
            confidence >= LanguageDetector.MIN_LINE_CONFIDENCE
            and counts.get(language.script, 0) / total >= LanguageDetector.MIN_LINE_SCRIPT_SHARE
        )

    @staticmethod
    def believable_lines(
        lines: tuple[tuple[str, float], ...], language: OcrComponentInfo
    ) -> list[tuple[str, float]]:
        return [
            (text, score)
            for text, score in lines
            if text.strip() and LanguageDetector.keep_line(text, score, language)
        ]

    @staticmethod
    def filter_pages(pages: list[PageResult], language: OcrComponentInfo) -> list[PageResult]:
        """`pages` with the lines `language` read unbelievably dropped from scanned pages.

        Used on a first-language read that was judged unsure, so the text a wrong-language pass
        made up never reaches the index. Native and mixed pages, and pages without line scores,
        are left as they are.
        """
        filtered = []
        for page in pages:
            if page.source != "ocr" or not page.lines:
                filtered.append(page)
                continue
            kept = LanguageDetector.believable_lines(page.lines, language)
            confidence = sum(score for _, score in kept) / len(kept) if kept else 0.0
            filtered.append(
                replace(
                    page,
                    text="\n".join(text for text, _ in kept),
                    confidence=confidence,
                    lines=tuple(kept),
                )
            )
        return filtered

    @staticmethod
    def languages_in_text(text: str, candidates: list[OcrComponentInfo]) -> list[str]:
        """The ids of the `candidates` whose script `text` contains - how a file with a text
        layer (no OCR) shows which language it is in."""
        present = Scripts.present(text)
        return [lang.id for lang in candidates if lang.script in present]
