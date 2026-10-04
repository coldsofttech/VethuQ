"""Which languages a file is read in, and what to do after the first one has read it.

`LanguagePlan.candidates` resolves what the user asked for: a flag on the run, else the source's
own languages, else the `ocr_languages` setting. One candidate is read directly. With several, the
first (the default language, English, unless it is not among them) reads the file; if it reads it
confidently that is the language, otherwise the rest are queued to read it too, in order. The
passes are recorded in `document_languages`; `vethuq_core.ocr.passes` runs the queued ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vethuq_core.languages import Candidates, Languages, LanguageSelection
from vethuq_core.ocr.catalog import OcrCatalog
from vethuq_core.ocr.detection import LanguageDetector
from vethuq_core.readers import PageResult
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Source
from vethuq_core.storage import Storage

# A file's passes as stored: (language, position, status, source, confidence).
LanguageRow = tuple[str, int, str, str, float | None]


@dataclass(frozen=True)
class FirstPass:
    """What to store after a file's first language has read it: the pages (with unbelievable
    lines dropped when the language was doubted) and the file's language passes."""

    pages: list[PageResult]
    rows: list[LanguageRow]


class LanguagePlan:
    # Pass statuses (`document_languages.status`).
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"
    # How a pass came to be (`document_languages.source`).
    DEFAULT = "default"
    AUTO = "auto"
    MANUAL = "manual"

    @staticmethod
    def candidates(
        storage: Storage, source: Source | None = None, override: str | Sequence[str] | None = None
    ) -> Candidates:
        """The languages `source`'s files may be read in, most specific choice first: `override`
        (a `--lang` flag), the source's own languages, then the global setting.

        Raises `LanguageUnavailableError` if a chosen language isn't installed or enabled and
        `UnknownLanguageError` for an id no manifest declares.
        """
        requested = LanguageSelection.parse(override)
        explicit = requested is not None
        if requested is None and source is not None and source.languages:
            requested = LanguageSelection.parse(source.languages)
            explicit = requested is not None
        if requested is None:
            requested = LanguageSelection.parse(OcrSettings.get_languages(storage))
        return LanguageSelection.resolve(
            requested, explicit=explicit, enabled=Languages.enabled_ids()
        )

    @staticmethod
    def _mean_confidence(pages: list[PageResult]) -> float | None:
        scanned = [page.confidence for page in pages if page.source == "ocr"]
        return sum(scanned) / len(scanned) if scanned else None

    @staticmethod
    def after_first_pass(candidates: Candidates, pages: list[PageResult]) -> FirstPass:
        """Decide what the first language's read means for the rest of the candidates.

        A single candidate is the language: nothing to detect. Several: the read is judged
        (`LanguageDetector.assess`). A file with a text layer shows its language by script, with
        no OCR to queue. A confident (or empty) read settles it and the other candidates are
        skipped. An unsure one keeps the first language's believable lines only and queues the
        other candidates, in order, to read the file as well.
        """
        first = OcrCatalog.language(candidates.first)
        assert first is not None
        confidence = LanguagePlan._mean_confidence(pages)

        if not candidates.needs_detection:
            return FirstPass(
                pages,
                [(first.id, 0, LanguagePlan.DONE, candidates.choice_source, confidence)],
            )

        assessment = LanguageDetector.assess(pages, first)
        if assessment.verdict == LanguageDetector.NATIVE:
            found = LanguageDetector.languages_in_text(
                "\n".join(page.text for page in pages),
                [lang for lang in map(OcrCatalog.language, candidates.ids) if lang is not None],
            )
            return FirstPass(
                pages,
                [
                    (
                        language_id,
                        position,
                        LanguagePlan.DONE if language_id in found else LanguagePlan.SKIPPED,
                        LanguagePlan.AUTO,
                        None,
                    )
                    for position, language_id in enumerate(candidates.ids)
                ],
            )
        if assessment.verdict in (LanguageDetector.CONFIDENT, LanguageDetector.EMPTY):
            return FirstPass(pages, LanguagePlan._settled(candidates, confidence))

        rows: list[LanguageRow] = [(first.id, 0, LanguagePlan.DONE, LanguagePlan.AUTO, confidence)]
        rows += [
            (language_id, position, LanguagePlan.PENDING, LanguagePlan.AUTO, None)
            for position, language_id in enumerate(candidates.rest, start=1)
        ]
        return FirstPass(LanguageDetector.filter_pages(pages, first), rows)

    @staticmethod
    def _settled(candidates: Candidates, confidence: float | None) -> list[LanguageRow]:
        rows: list[LanguageRow] = [
            (candidates.first, 0, LanguagePlan.DONE, LanguagePlan.AUTO, confidence)
        ]
        rows += [
            (language_id, position, LanguagePlan.SKIPPED, LanguagePlan.AUTO, None)
            for position, language_id in enumerate(candidates.rest, start=1)
        ]
        return rows
