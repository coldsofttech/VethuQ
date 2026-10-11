"""Saving the pages of a document, one at a time as they are read."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vethuq._db import _DocumentLanguage, _PdfPage, _PdfPageQuick
from vethuq._db.values import _PageSource, _PageState, _PassSource, _PassStatus
from vethuq._ocr import _PageResult


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _PageStore:
    # ----- reading ----------------------------------------------------------------------------

    @staticmethod
    def pages(session: Session, document_id: int) -> dict[int, _PdfPage]:
        return {
            p.page_number: p
            for p in session.scalars(select(_PdfPage).where(_PdfPage.document_id == document_id))
        }

    @staticmethod
    def read_in(session: Session, document_id: int, language_id: int) -> set[int]:
        """The pages OCR has already read in this language."""
        return set(
            session.scalars(
                select(_PdfPage.page_number)
                .join(_PdfPageQuick, _PdfPageQuick.page_id == _PdfPage.id)
                .where(
                    _PdfPage.document_id == document_id,
                    _PdfPageQuick.language_id == language_id,
                )
            )
        )

    @staticmethod
    def pass_row(session: Session, document_id: int, language_id: int) -> _DocumentLanguage | None:
        return session.get(_DocumentLanguage, (document_id, language_id))

    @staticmethod
    def covers(session: Session, document_id: int, language_id: int) -> bool:
        """Whether a document has already been read for `language_id`: it was read in it, or
        none of its pages needed OCR."""
        done = _PageStore.pass_row(session, document_id, language_id)
        if done is not None and done.status is _PassStatus.DONE:
            return True
        any_language = session.scalars(
            select(_DocumentLanguage).where(
                _DocumentLanguage.document_id == document_id,
                _DocumentLanguage.status == _PassStatus.DONE,
            )
        ).first()
        if any_language is None:
            return False
        sources = session.scalars(
            select(_PdfPage.source).where(_PdfPage.document_id == document_id)
        )
        return all(s is _PageSource.NATIVE for s in sources)

    @staticmethod
    def read_before(session: Session, document_id: int, language_id: int) -> bool:
        """Whether the document was fully read in another language (so this one is an additional
        language, priced as such)."""
        return (
            session.scalars(
                select(_DocumentLanguage).where(
                    _DocumentLanguage.document_id == document_id,
                    _DocumentLanguage.language_id != language_id,
                    _DocumentLanguage.status == _PassStatus.DONE,
                )
            ).first()
            is not None
        )

    @staticmethod
    def waiting(session: Session, document_id: int) -> int:
        """Pages of a document whose OCR is still to come."""
        return int(
            session.scalar(
                select(func.count())
                .select_from(_PdfPage)
                .where(_PdfPage.document_id == document_id, _PdfPage.status != _PageState.DONE)
            )
            or 0
        )

    # ----- the pass ---------------------------------------------------------------------------

    @staticmethod
    def begin_pass(
        session: Session, document_id: int, language_id: int, *, manual: bool
    ) -> _DocumentLanguage:
        row = _PageStore.pass_row(session, document_id, language_id)
        if row is None:
            row = _DocumentLanguage(document_id=document_id, language_id=language_id)
            session.add(row)
        if row.status is not _PassStatus.PROCESSING or row.started_at is None:
            row.started_at = _now()
        row.status = _PassStatus.PROCESSING
        row.source = _PassSource.MANUAL if manual else _PassSource.DEFAULT
        row.error_message, row.completed_at = None, None
        session.flush()
        return row

    @staticmethod
    def fail_pass(session: Session, document_id: int, language_id: int, message: str) -> None:
        row = _PageStore.pass_row(session, document_id, language_id)
        if row is not None and row.status is not _PassStatus.DONE:
            row.status, row.error_message, row.completed_at = _PassStatus.ERROR, message, _now()
            session.flush()

    @staticmethod
    def finish_pass(session: Session, document_id: int, language_id: int) -> float | None:
        """Mark the document read in this language; returns its average confidence."""
        average = session.scalar(
            select(func.avg(_PdfPage.confidence)).where(_PdfPage.document_id == document_id)
        )
        row = _PageStore.pass_row(session, document_id, language_id)
        assert row is not None  # noqa: S101 - a pass is begun before it is finished
        row.status, row.confidence, row.completed_at = _PassStatus.DONE, average, _now()
        row.error_message = None
        session.flush()
        return average

    # ----- one page ---------------------------------------------------------------------------

    @staticmethod
    def _quick(session: Session, page: _PdfPage, language_id: int, result: _PageResult) -> None:
        quick = result.quick
        if quick is None:
            return
        row = session.scalars(
            select(_PdfPageQuick).where(
                _PdfPageQuick.page_id == page.id, _PdfPageQuick.language_id == language_id
            )
        ).first()
        if row is None:
            row = _PdfPageQuick(page_id=page.id, language_id=language_id, completed_at=_now())
            session.add(row)
        row.region_count, row.engine = quick.region_count, quick.engine
        row.confidence, row.line_count = quick.confidence, quick.line_count
        row.char_count, row.duration_ms = quick.char_count, quick.duration_ms
        row.completed_at = _now()

    @staticmethod
    def save_page(
        session: Session, document_id: int, result: _PageResult, language_id: int
    ) -> _PdfPage:
        """Save a page as read. A page the document already has (read in another language, or
        staged) keeps its text, with this language's added when it isn't there already."""
        page = session.scalars(
            select(_PdfPage).where(
                _PdfPage.document_id == document_id, _PdfPage.page_number == result.page_number
            )
        ).first()
        if page is None:
            page = _PdfPage(
                document_id=document_id,
                page_number=result.page_number,
                text=result.text,
                char_count=len(result.text),
                confidence=result.confidence,
                source=result.source,
                image_width=result.image_width,
                image_height=result.image_height,
                status=_PageState.WAITING if result.pending else _PageState.DONE,
            )
            session.add(page)
        elif not result.pending and result.quick is not None:
            if page.status is _PageState.DONE:  # an earlier language's text: add to it
                added = result.text
                if added and added not in page.text:
                    page.text = f"{page.text}\n{added}" if page.text else added
                    page.char_count = len(page.text)
            else:  # this page was waiting for its first read
                page.text, page.char_count = result.text, len(result.text)
                page.confidence, page.source = result.confidence, result.source
                page.image_width = result.image_width or page.image_width
                page.image_height = result.image_height or page.image_height
                page.status = _PageState.DONE
        session.flush()
        if not result.pending:
            _PageStore._quick(session, page, language_id, result)
            session.flush()
        return page
