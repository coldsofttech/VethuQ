"""The record of index runs."""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import psutil
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vethuq._db import _DocumentIndex, _IndexRun, _RemoteJobPage, _Source
from vethuq._db.values import _JobPageState
from vethuq._documents import _Documents
from vethuq._errors import _IndexAlreadyRunningError, _IndexRunNotFoundError
from vethuq.enums import FileStatus, IndexRunSortBy, IndexRunStatus, SortOrder


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


class _Runs:
    @staticmethod
    def _now() -> str:
        return _stamp()

    _logger = logging.getLogger("vethuq.indexing")
    _active: set[int] = set()  # runs going in this process
    _guard = threading.Lock()

    # ----- starting and finishing -------------------------------------------------------------

    @staticmethod
    def _alive(run: _IndexRun) -> bool:
        if run.pid is None:
            return False
        if run.pid == os.getpid():
            return run.id in _Runs._active
        return psutil.pid_exists(run.pid)

    @staticmethod
    def stale_processing(session: Session) -> list[_DocumentIndex]:
        """Files marked processing that nothing is working on: not the ones whose pages are away
        in a remote job that is still open."""
        away = select(_RemoteJobPage.document_id).where(_RemoteJobPage.state == _JobPageState.SENT)
        return list(
            session.scalars(
                select(_DocumentIndex).where(
                    _DocumentIndex.status == FileStatus.PROCESSING,
                    or_(
                        _DocumentIndex.document_id.is_(None),
                        _DocumentIndex.document_id.not_in(away),
                    ),
                )
            )
        )

    @staticmethod
    def recover(session: Session) -> bool:
        """Fail the runs whose process is gone, and put back the files they were reading.
        Returns whether a run is really going."""
        live = False
        for run in session.scalars(
            select(_IndexRun).where(_IndexRun.status == IndexRunStatus.RUNNING)
        ):
            if _Runs._alive(run):
                live = True
                continue
            run.status, run.completed_at = IndexRunStatus.FAILED, _stamp()
            run.error = "The process running it ended before it finished."
            _Runs._logger.warning("Index run %d was left running and has been failed", run.id)
        session.flush()
        if not live:
            stale = _Runs.stale_processing(session)
            for row in stale:
                row.status = FileStatus.PENDING
            session.flush()
            for source_id in {row.source_id for row in stale}:
                _Documents.refresh_source(session, source_id)
        return live

    @staticmethod
    def begin(
        session: Session,
        source_id: int | None,
        file_path: str | None,
        workers: int,
        tier: str = "local",
        mode: str = "run",
    ) -> _IndexRun:
        if _Runs.recover(session):
            raise _IndexAlreadyRunningError(
                "An index run is already going.", "Wait for it to finish, then run again."
            )
        run = _IndexRun(
            source_id=source_id,
            file_path=file_path,
            status=IndexRunStatus.RUNNING,
            workers=workers,
            workers_active=workers,
            tier=tier,
            mode=mode,
            pid=os.getpid(),
            started_at=_stamp(),
        )
        session.add(run)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            raise _IndexAlreadyRunningError(
                "An index run is already going.", "Wait for it to finish, then run again."
            ) from None
        with _Runs._guard:
            _Runs._active.add(run.id)
        return run

    @staticmethod
    def end(run_id: int) -> None:
        with _Runs._guard:
            _Runs._active.discard(run_id)

    # ----- control ----------------------------------------------------------------------------

    @staticmethod
    def going(session: Session) -> _IndexRun | None:
        """The run that is going (here or in another process), or None."""
        for run in session.scalars(
            select(_IndexRun).where(_IndexRun.status == IndexRunStatus.RUNNING)
        ):
            if _Runs._alive(run):
                return run
        return None

    # ----- reading ----------------------------------------------------------------------------

    @staticmethod
    def get(session: Session, run_id: int) -> _IndexRun:
        if isinstance(run_id, bool) or not isinstance(run_id, int):
            raise TypeError("A run is identified by its id (int).")
        run = session.get(_IndexRun, run_id)
        if run is None:
            raise _IndexRunNotFoundError(
                f"No index run has id {run_id}.", "Use index.history() to see the runs."
            )
        return run

    @staticmethod
    def source_path(session: Session, run: _IndexRun) -> str | None:
        if run.source_id is None:
            return None
        source = session.get(_Source, run.source_id)
        return source.path if source is not None else None

    @staticmethod
    def _moment(value: datetime | str, name: str) -> str:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                raise ValueError(f"{name} must be a datetime or an ISO 8601 string.") from None
        if not isinstance(value, datetime):
            raise TypeError(f"{name} must be a datetime or an ISO 8601 string.")
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def history(
        session: Session,
        *,
        target: int | str | Path | None = None,
        status: IndexRunStatus | str | None = None,
        started_after: datetime | str | None = None,
        started_before: datetime | str | None = None,
        sort_by: IndexRunSortBy | str = IndexRunSortBy.STARTED_AT,
        order: SortOrder | str = SortOrder.DESC,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[_IndexRun]:
        from vethuq._sources import _Sources  # noqa: PLC0415 - avoids an import cycle

        sort = _Sources._coerce(IndexRunSortBy, sort_by, "sort_by")  # type: ignore[type-var]
        direction = _Sources._coerce(SortOrder, order, "order")
        statement = select(_IndexRun)
        if status is not None:
            statement = statement.where(
                _IndexRun.status == _Sources._coerce(IndexRunStatus, status, "status")  # type: ignore[type-var]
            )
        if target is not None:
            if isinstance(target, bool) or not isinstance(target, int | str | Path):
                raise TypeError("A target is a source id (int) or a path (str or Path).")
            if isinstance(target, int):
                statement = statement.where(_IndexRun.source_id == target)
            else:
                resolved = str(Path(target).expanduser().resolve())
                source_ids = select(_Source.id).where(_Source.path == resolved)
                statement = statement.where(
                    (_IndexRun.source_id.in_(source_ids)) & (_IndexRun.file_path.is_(None))
                    | (_IndexRun.file_path == resolved)
                )
        if started_after is not None:
            statement = statement.where(
                _IndexRun.started_at >= _Runs._moment(started_after, "started_after")
            )
        if started_before is not None:
            statement = statement.where(
                _IndexRun.started_at <= _Runs._moment(started_before, "started_before")
            )
        column = {
            IndexRunSortBy.FILES_TOTAL: _IndexRun.total_files,
            IndexRunSortBy.FILES_PROCESSED: _IndexRun.processed_files,
            IndexRunSortBy.FILES_FAILED: _IndexRun.failed_files,
        }.get(sort) or getattr(_IndexRun, sort.value)
        statement = statement.order_by(
            column.desc() if direction is SortOrder.DESC else column.asc(),
            _IndexRun.id.desc() if direction is SortOrder.DESC else _IndexRun.id.asc(),
        )
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return list(session.scalars(statement))
