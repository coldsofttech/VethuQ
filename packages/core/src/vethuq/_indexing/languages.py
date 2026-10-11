"""Which languages a file is read in, and what to do once the first one has read it.

The candidates are what the caller asked for: a `languages=` on the run, else the source's own
languages, else the default languages setting. With one candidate that is the language. With
several, the first (the system default language, English, unless it is not among them) reads the
file; if it reads it confidently that is the language, otherwise the rest are queued to read it
too (`document_languages` rows, pending, in order). A file with a text layer shows its language by
the scripts in its text. The queued passes run in `_Passes`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from vethuq._db import _DocumentLanguage, _Language, _PdfPage, _Source
from vethuq._db.values import _PageSource, _PassSource, _PassStatus
from vethuq._languages import _Languages
from vethuq._ocr import _LanguageDetector, _Scripts
from vethuq_addon_api import LanguageSpec


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class _Candidates:
    """The languages a file may be read in, the one that reads it first and the rest."""

    first: LanguageSpec
    rest: tuple[LanguageSpec, ...]
    explicit: bool  # the caller chose them (a run's languages, or the source's own)

    @property
    def codes(self) -> list[str]:
        return [self.first.id, *(spec.id for spec in self.rest)]

    @property
    def needs_detection(self) -> bool:
        return bool(self.rest)


class _LanguagePlan:
    @staticmethod
    def candidates(
        session: Session,
        specs: list[LanguageSpec],
        source: _Source,
        override: list[str] | None = None,
    ) -> _Candidates:
        """The candidates for a file of `source`. Raises `LanguageUnavailableError` for an
        override naming a language that can't be used."""
        if override:
            codes, explicit = _Languages.clean(override), True
            _Languages.validate(session, specs, codes)
        elif source.language_codes:
            codes, explicit = list(source.language_codes), True
        else:
            codes, explicit = _Languages.default_ids(session, specs), False
        by_id = {spec.id: spec for spec in specs}
        chosen = [by_id[code] for code in codes if code in by_id]
        if not chosen:
            raise KeyError(codes[0] if codes else "")
        default = next((spec for spec in chosen if spec.default), None)
        first = default or chosen[0]
        rest = tuple(spec for spec in chosen if spec.id != first.id)
        return _Candidates(first, rest, explicit)

    # ----- after the first language has read the file -----------------------------------------

    @staticmethod
    def settle(
        session: Session,
        document_id: int,
        first_id: int,
        specs: list[LanguageSpec],
    ) -> None:
        """Decide what the first language's read means for the other candidates, and note the
        languages the file's text layer is in.

        With one candidate there is nothing to detect. A confident (or empty) read settles it and
        the others are skipped. An unsure one keeps the first language's believable lines only
        (when the lines are known) and queues the others, in order, to read the file as well. A
        file with a text layer shows its language by its scripts.
        """
        first_row = session.get(_DocumentLanguage, (document_id, first_id))
        pages = list(session.scalars(select(_PdfPage).where(_PdfPage.document_id == document_id)))
        codes_by_id = {
            row.id: row.language for row in session.scalars(select(_Language))
        }  # language id -> code
        ids_by_code = {code: language_id for language_id, code in codes_by_id.items()}
        by_id = {spec.id: spec for spec in specs}
        first_spec = by_id.get(codes_by_id.get(first_id, ""))
        if first_spec is None:
            return
        wanted = [c for c in (first_row.candidates.split(",") if first_row else []) if c]
        if len(wanted) > 1:
            _LanguagePlan._detect(
                session, document_id, first_spec, wanted, pages, ids_by_code, by_id
            )
        _LanguagePlan._tag_text_layer(session, document_id, first_id, pages, ids_by_code, specs)
        for page in pages:
            page.read_lines = None  # judged: the lines are not needed any more
        session.flush()

    @staticmethod
    def _detect(
        session: Session,
        document_id: int,
        first: LanguageSpec,
        codes: list[str],
        pages: list[_PdfPage],
        ids_by_code: dict[str, int],
        by_id: dict[str, LanguageSpec],
    ) -> None:
        rest = [c for c in codes if c != first.id and c in by_id and c in ids_by_code]
        assessment = _LanguageDetector.assess(
            [(p.source is _PageSource.OCR, p.text, p.confidence) for p in pages], first
        )
        if assessment.verdict == _LanguageDetector.NATIVE:
            text = "\n".join(p.text for p in pages)
            found = _Scripts.present(text, [by_id[c] for c in codes if c in by_id])
            for position, code in enumerate(rest, start=1):
                status = _PassStatus.DONE if code in found else _PassStatus.SKIPPED
                _LanguagePlan._row(session, document_id, ids_by_code[code], position, status)
            return
        if assessment.verdict in (_LanguageDetector.CONFIDENT, _LanguageDetector.EMPTY):
            for position, code in enumerate(rest, start=1):
                _LanguagePlan._row(
                    session, document_id, ids_by_code[code], position, _PassStatus.SKIPPED
                )
            return
        # Unsure: what the first language made up is not kept, and the others read the file too.
        for page in pages:
            if page.source is _PageSource.OCR and page.read_lines:
                lines = [(text, float(score)) for text, score in json.loads(page.read_lines)]
                kept = _LanguageDetector.believable(lines, first)
                page.text = "\n".join(text for text, _ in kept)
                page.char_count = len(page.text)
                page.confidence = sum(score for _, score in kept) / len(kept) if kept else 0.0
        for position, code in enumerate(rest, start=1):
            _LanguagePlan._row(
                session, document_id, ids_by_code[code], position, _PassStatus.PENDING
            )

    @staticmethod
    def _tag_text_layer(
        session: Session,
        document_id: int,
        first_id: int,
        pages: list[_PdfPage],
        ids_by_code: dict[str, int],
        specs: list[LanguageSpec],
    ) -> None:
        """A page whose text came from the file was not read in any language, so nothing recorded
        one: it is in the languages whose script its text contains (so a search by language finds
        a native Telugu PDF)."""
        text = "\n".join(
            p.text for p in pages if p.source in (_PageSource.NATIVE, _PageSource.MIXED)
        )
        if not text.strip():
            return
        taken = {
            row.language_id
            for row in session.scalars(
                select(_DocumentLanguage).where(_DocumentLanguage.document_id == document_id)
            )
        }
        usable = [spec for spec in specs if spec.available and spec.id in ids_by_code]
        position = len(taken)
        for code in _Scripts.present(text, usable):
            language_id = ids_by_code[code]
            if language_id in taken or language_id == first_id:
                continue
            session.add(
                _DocumentLanguage(
                    document_id=document_id,
                    language_id=language_id,
                    position=position,
                    status=_PassStatus.DONE,
                    source=_PassSource.AUTO,
                    started_at=_now(),
                    completed_at=_now(),
                )
            )
            position += 1

    @staticmethod
    def _row(
        session: Session,
        document_id: int,
        language_id: int,
        position: int,
        status: _PassStatus,
    ) -> None:
        """A pass row for the detection, left alone if the language has already been read."""
        row = session.get(_DocumentLanguage, (document_id, language_id))
        if row is None:
            row = _DocumentLanguage(document_id=document_id, language_id=language_id)
            session.add(row)
        elif row.status in (_PassStatus.DONE, _PassStatus.PROCESSING):
            return
        row.position, row.status, row.source = position, status, _PassSource.AUTO
        row.error_message = None
        if status is _PassStatus.DONE:
            row.started_at = row.completed_at = _now()
