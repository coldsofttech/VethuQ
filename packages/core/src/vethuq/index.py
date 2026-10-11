"""Indexing: reading sources into searchable pages: `VethuQ().index`.

    run = client.index.run()                 # every source
    run = client.index.run("~/docs")         # one source
    run = client.index.run("~/docs/a.pdf")   # one file in a source

A run reads each file's text layer first, and runs OCR only on the pages and images that need it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vethuq._db import _Database, _IndexRun
from vethuq._indexing import _Indexer, _Runs
from vethuq._metrics import _Metrics
from vethuq.enums import IndexRunSortBy, IndexRunStatus, SortOrder

__all__ = ["Index", "IndexRun", "IndexRunSortBy", "IndexRunStatus", "SortOrder"]


@dataclass(frozen=True)
class IndexRun:
    """One run of the indexer."""

    id: int
    source_id: int | None  # the source it indexed; None for a run of every source
    target: str | None  # the source's path, or the file's; None for every source
    file_path: str | None  # the file, for a run of a single file
    status: IndexRunStatus
    files_total: int  # the files it had to do
    files_processed: int
    files_failed: int
    pages_processed: int  # pages read in this run
    ocr_pages: int  # of those, the pages that needed OCR
    credits_charged: float  # what the run cost
    workers: int
    started_at: str  # UTC, ISO 8601
    completed_at: str | None
    error: str | None

    @classmethod
    def _from_model(cls, model: _IndexRun, source_path: str | None) -> IndexRun:
        return cls(
            id=model.id,
            source_id=model.source_id,
            target=model.file_path or source_path,
            file_path=model.file_path,
            status=model.status,
            files_total=model.total_files,
            files_processed=model.processed_files,
            files_failed=model.failed_files,
            pages_processed=model.processed_pages,
            ocr_pages=model.ocr_pages,
            credits_charged=model.credits_milli / 1000,
            workers=model.workers,
            started_at=model.started_at,
            completed_at=model.completed_at,
            error=model.error,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target": self.target,
            "file_path": self.file_path,
            "status": self.status.value,
            "files_total": self.files_total,
            "files_processed": self.files_processed,
            "files_failed": self.files_failed,
            "pages_processed": self.pages_processed,
            "ocr_pages": self.ocr_pages,
            "credits_charged": self.credits_charged,
            "workers": self.workers,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Index:
    """Index sources, and look back at the runs.

    Not created directly: use `VethuQ().index`.
    """

    def __init__(self, database: _Database, indexer: _Indexer, metrics: _Metrics) -> None:
        self._database = database
        self._indexer = indexer
        self._metrics = metrics

    def run(
        self, target: int | str | Path | None = None, *, workers: int | str | None = None
    ) -> IndexRun:
        """Index files and wait until the run is over; return it.

        `target` is a source (its id or path), a file inside an active source (its path), or left
        out for every active source. The run picks up new and modified files, files that failed
        before, and files that weren't readable until an add-on was installed; files already
        indexed are left alone. `workers` is how many files are read at once: `"auto"`, or 0 to 8
        (0 reads on this thread); left out, the setting `settings.index` applies. Pages that need
        OCR cost credits (see `credits`); if they run out the run ends as `WAITING_CREDITS` and
        the next run, after they reset at 00:00 UTC, carries on. At the end, if you opted in, a
        batch of anonymous metrics is sent (see `metrics`). A file that
        fails doesn't stop the run: see its `files_failed` and the file's `index.error`.

        Raises `IndexAlreadyRunningError` if a run is going, `SourceNotFoundError` if `target`
        isn't a source or a file in one, and `SourcePathError` if the source is gone from disk.
        """
        run_id = self._indexer.run(target, workers)
        self._metrics.send()  # if you opted in; at most once a day; never raises
        return self.get(run_id)

    def get(self, run_id: int) -> IndexRun:
        """One run by id. Raises `IndexRunNotFoundError` if there is none."""
        with self._database.session() as session:
            model = _Runs.get(session, run_id)
            return IndexRun._from_model(model, _Runs.source_path(session, model))

    def history(
        self,
        target: int | str | Path | None = None,
        status: IndexRunStatus | str | None = None,
        started_after: datetime | str | None = None,
        started_before: datetime | str | None = None,
        sort_by: IndexRunSortBy | str = IndexRunSortBy.STARTED_AT,
        order: SortOrder | str = SortOrder.DESC,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[IndexRun]:
        """The runs, newest first unless sorted otherwise.

        `target` keeps the runs of a source (id or path) or of a file. `status` keeps one
        `IndexRunStatus`; `started_after` / `started_before` (a `datetime`, naive meaning UTC, or
        an ISO 8601 string) bound when they started. `limit` and `offset` page the result.
        Raises `ValueError` for a value that isn't valid.
        """
        with self._database.session() as session:
            models = _Runs.history(
                session,
                target=target,
                status=status,
                started_after=started_after,
                started_before=started_before,
                sort_by=sort_by,
                order=order,
                limit=limit,
                offset=offset,
            )
            return [IndexRun._from_model(m, _Runs.source_path(session, m)) for m in models]
