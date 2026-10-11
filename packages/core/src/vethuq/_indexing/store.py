"""Saving the pages of a document."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from vethuq._db import _DocumentLanguage, _PdfPage, _PdfPageQuick
from vethuq._db.values import _PageSource, _PassSource, _PassStatus
from vethuq._ocr import _PageResult


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _PageStore:
    @staticmethod
    def sources(session: Session, document_id: int) -> dict[int, _PageSource]:
        """How each page of a document was read, by page number."""
        return dict(
            session.execute(
                select(_PdfPage.page_number, _PdfPage.source).where(
                    _PdfPage.document_id == document_id
                )
            ).all()
        )

    @staticmethod
    def _quick(page_id: int, language_id: int, result: _PageResult) -> _PdfPageQuick | None:
        quick = result.quick
        if quick is None:
            return None
        return _PdfPageQuick(
            page_id=page_id,
            language_id=language_id,
            region_count=quick.region_count,
            engine=quick.engine,
            confidence=quick.confidence,
            line_count=quick.line_count,
            char_count=quick.char_count,
            duration_ms=quick.duration_ms,
            completed_at=_now(),
        )

    @staticmethod
    def replace(
        session: Session, document_id: int, results: list[_PageResult], language_id: int
    ) -> None:
        """Save a document's pages as read, replacing any it had."""
        session.execute(delete(_PdfPage).where(_PdfPage.document_id == document_id))
        for result in results:
            page = _PdfPage(
                document_id=document_id,
                page_number=result.page_number,
                text=result.text,
                char_count=len(result.text),
                confidence=result.confidence,
                source=result.source,
                image_width=result.image_width,
                image_height=result.image_height,
            )
            session.add(page)
            session.flush()
            quick = _PageStore._quick(page.id, language_id, result)
            if quick is not None:
                session.add(quick)
        session.flush()

    @staticmethod
    def merge(
        session: Session, document_id: int, results: list[_PageResult], language_id: int
    ) -> None:
        """Add a new language's reading of a document's image pages to its text."""
        pages = {
            p.page_number: p
            for p in session.scalars(select(_PdfPage).where(_PdfPage.document_id == document_id))
        }
        for result in results:
            page = pages.get(result.page_number)
            if page is None or result.quick is None:
                continue
            added = result.text
            if added and added not in page.text:
                page.text = f"{page.text}\n{added}" if page.text else added
                page.char_count = len(page.text)
            quick = _PageStore._quick(page.id, language_id, result)
            if quick is not None:
                session.add(quick)
        session.flush()

    @staticmethod
    def covers(session: Session, document_id: int, language_id: int) -> bool:
        """Whether a document has already been read for `language_id`: it was read in it, or
        none of its pages needed OCR."""
        done = session.get(_DocumentLanguage, (document_id, language_id))
        if done is not None and done.status is _PassStatus.DONE:
            return True
        sources = _PageStore.sources(session, document_id)
        any_language = session.scalars(
            select(_DocumentLanguage).where(
                _DocumentLanguage.document_id == document_id,
                _DocumentLanguage.status == _PassStatus.DONE,
            )
        ).first()
        return any_language is not None and all(s is _PageSource.NATIVE for s in sources.values())

    @staticmethod
    def mark_language(
        session: Session,
        document_id: int,
        language_id: int,
        *,
        manual: bool,
        confidence: float | None,
        started_at: str,
    ) -> None:
        row = session.get(_DocumentLanguage, (document_id, language_id))
        if row is None:
            row = _DocumentLanguage(document_id=document_id, language_id=language_id)
            session.add(row)
        row.status = _PassStatus.DONE
        row.source = _PassSource.MANUAL if manual else _PassSource.DEFAULT
        row.confidence = confidence
        row.error_message = None
        row.started_at, row.completed_at = started_at, _now()
        session.flush()
