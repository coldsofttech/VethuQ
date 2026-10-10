"""The document index: which files a source holds, and where each is in indexing.

Rows are written by the indexer (and by tests); `list_files(detailed=True)` only reads them. Every
change to a row refreshes its source's overall status and file counts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vethuq._db import _Document, _DocumentIndex, _Source
from vethuq.enums import FileStatus, SourceStatus


class _Documents:
    _logger = logging.getLogger("vethuq.database")

    # The files that count towards a source's progress: not unsupported, not removed.
    COUNTED = (
        FileStatus.PENDING,
        FileStatus.PROCESSING,
        FileStatus.MODIFIED,
        FileStatus.INDEXED,
        FileStatus.ERROR,
    )
    DONE = (FileStatus.INDEXED, FileStatus.ERROR)
    WAITING = (FileStatus.PENDING, FileStatus.PROCESSING, FileStatus.MODIFIED)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    # ----- reading --------------------------------------------------------------------------

    @staticmethod
    def rows(session: Session, source_id: int) -> list[_DocumentIndex]:
        """Every file row of a source, by id."""
        return list(
            session.scalars(
                select(_DocumentIndex)
                .where(_DocumentIndex.source_id == source_id)
                .order_by(_DocumentIndex.id)
            )
        )

    @staticmethod
    def find(session: Session, file_path: str) -> _DocumentIndex | None:
        return session.scalars(
            select(_DocumentIndex).where(_DocumentIndex.file_path == file_path)
        ).first()

    @staticmethod
    def original_paths(session: Session, document_ids: set[int]) -> dict[int, tuple[int, str]]:
        """For each document, its original: the id and path of its earliest file row."""
        if not document_ids:
            return {}
        earliest = (
            select(func.min(_DocumentIndex.id))
            .where(_DocumentIndex.document_id.in_(document_ids))
            .group_by(_DocumentIndex.document_id)
            .scalar_subquery()
        )
        rows = session.execute(
            select(_DocumentIndex.document_id, _DocumentIndex.id, _DocumentIndex.file_path).where(
                _DocumentIndex.id.in_(earliest)
            )
        )
        return {document_id: (row_id, path) for document_id, row_id, path in rows}

    # ----- writing --------------------------------------------------------------------------

    @staticmethod
    def register(
        session: Session, source: _Source, file_path: str, size_bytes: int, modified_at: str
    ) -> _DocumentIndex:
        """Record that a source holds this file, as it is now. Safe to repeat.

        A new file is pending. A known file whose size or time changed becomes modified (so it is
        processed again); one that was removed and is back on disk becomes pending.
        """
        row = _Documents.find(session, file_path)
        if row is None:
            row = _DocumentIndex(
                source_id=source.id,
                file_path=file_path,
                status=FileStatus.PENDING,
                size_bytes=size_bytes,
                modified_at=modified_at,
                discovered_at=_Documents._now(),
            )
            session.add(row)
        elif row.source_id != source.id:
            raise ValueError(f"{file_path} already belongs to source {row.source_id}")
        else:
            changed = row.size_bytes != size_bytes or row.modified_at != modified_at
            if row.status is FileStatus.REMOVED:
                row.status, row.removed_at = FileStatus.PENDING, None
            elif changed and row.status in (*_Documents.DONE, FileStatus.PROCESSING):
                row.status = FileStatus.MODIFIED
            row.size_bytes, row.modified_at = size_bytes, modified_at
        session.flush()
        _Documents.refresh_source(session, source.id)
        return row

    @staticmethod
    def start(session: Session, row: _DocumentIndex) -> None:
        row.status = FileStatus.PROCESSING
        row.started_at, row.completed_at, row.error_message = _Documents._now(), None, None
        _Documents._changed(session, row)

    @staticmethod
    def finish(session: Session, row: _DocumentIndex, sha256: str) -> None:
        """The file is indexed. Files with the same content share one document."""
        document = session.scalars(select(_Document).where(_Document.sha256 == sha256)).first()
        if document is None:
            document = _Document(sha256=sha256, created_at=_Documents._now())
            session.add(document)
            session.flush()
        now = _Documents._now()
        row.document_id, row.sha256 = document.id, sha256
        row.status, row.error_message = FileStatus.INDEXED, None
        row.completed_at = row.indexed_at = now
        _Documents._changed(session, row)

    @staticmethod
    def fail(session: Session, row: _DocumentIndex, message: str) -> None:
        row.status, row.error_message = FileStatus.ERROR, message
        row.completed_at = _Documents._now()
        row.retry_count += 1
        _Documents._changed(session, row)

    @staticmethod
    def mark_removed(session: Session, row: _DocumentIndex) -> None:
        """The file is gone from disk. The row stays until the source is purged."""
        row.status, row.removed_at = FileStatus.REMOVED, _Documents._now()
        _Documents._changed(session, row)

    @staticmethod
    def _changed(session: Session, row: _DocumentIndex) -> None:
        session.flush()
        _Documents.refresh_source(session, row.source_id)

    # ----- the source's overall state -------------------------------------------------------

    @staticmethod
    def overall(counts: dict[FileStatus, int]) -> tuple[SourceStatus, int, int]:
        """A source's status, files total and files processed, from its files' counts.

        Nothing counted, or nothing started yet: pending. Files still to do after some work:
        in progress. All done: completed, or error if any failed.
        """
        total = sum(counts.get(status, 0) for status in _Documents.COUNTED)
        done = sum(counts.get(status, 0) for status in _Documents.DONE)
        waiting = sum(counts.get(status, 0) for status in _Documents.WAITING)
        if total == 0:
            return SourceStatus.PENDING, 0, 0
        if waiting:
            started = done or counts.get(FileStatus.PROCESSING, 0)
            return (SourceStatus.IN_PROGRESS if started else SourceStatus.PENDING), total, done
        if counts.get(FileStatus.ERROR, 0):
            return SourceStatus.ERROR, total, done
        return SourceStatus.COMPLETED, total, done

    @staticmethod
    def refresh_source(session: Session, source_id: int) -> None:
        """Recompute a source's status and file counts from its files."""
        source = session.get(_Source, source_id)
        if source is None:
            return
        counts = dict(
            session.execute(
                select(_DocumentIndex.status, func.count())
                .where(_DocumentIndex.source_id == source_id)
                .group_by(_DocumentIndex.status)
            ).all()
        )
        status, total, done = _Documents.overall(counts)
        source.files_total, source.files_processed = total, done
        source.status = status if source.is_active else SourceStatus.REMOVED
        session.flush()

    # ----- purging --------------------------------------------------------------------------

    @staticmethod
    def purge_source(session: Session, source_id: int) -> None:
        """Delete a source's file rows, and the documents no file refers to any more."""
        for row in _Documents.rows(session, source_id):
            session.delete(row)
        session.flush()
        orphans = select(_Document).where(
            ~select(_DocumentIndex.id).where(_DocumentIndex.document_id == _Document.id).exists()
        )
        for document in session.scalars(orphans):
            session.delete(document)
        session.flush()
