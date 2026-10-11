"""How long an index run has left, worked out from what earlier runs took.

Local OCR is sized from `usage_daily` (seconds per OCR page, per file type) and from how many
pages, and how many of them needed OCR, the files indexed before had. Pages away on a remote tier
are sized from the time its earlier jobs took (`remote_jobs`: submitted to completed). Nothing is
timed during the run itself, so an estimate exists before the first file is done. A part with no
history cannot be estimated: it is left out and the result says it is not `complete`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vethuq._db import _DocumentIndex, _IndexRun, _PdfPage, _RemoteJob, _UsageDaily
from vethuq._db.values import _PageSource
from vethuq._filetypes import _FileTypeCatalog
from vethuq.enums import FileStatus, IndexRunStatus, RemoteJobStatus


@dataclass(frozen=True)
class _EtaResult:
    local_seconds: float = 0.0
    remote_seconds: float = 0.0
    complete: bool = True
    by_file_type: dict[str, float] = field(default_factory=dict)

    @property
    def seconds(self) -> float:
        return self.local_seconds + self.remote_seconds


class _Eta:
    # Recent speed says most about this machine and these models; with none, all time is used.
    WINDOW_DAYS = 30
    # The files indexed most recently that say how many pages a file of a type has.
    SAMPLE_FILES = 500
    LOCAL = "local"

    def __init__(self, catalog: _FileTypeCatalog) -> None:
        self.catalog = catalog

    # ----- the estimate -----------------------------------------------------------------------

    def estimate(self, session: Session, run: _IndexRun, active: bool) -> _EtaResult:
        """What `run` still has to do: its unfinished files (while it is `active`) and the remote
        jobs that are still out."""
        local, by_type, complete = 0.0, {}, True
        remote_pages = False
        if active:
            local, by_type, complete, remote_pages = self._local(session, run)
        remote, remote_complete = self._remote(session, run, remote_pages)
        return _EtaResult(local, remote, complete and remote_complete, by_type)

    # ----- local OCR --------------------------------------------------------------------------

    def _local(
        self, session: Session, run: _IndexRun
    ) -> tuple[float, dict[str, float], bool, bool]:
        remaining = self._remaining(session, run)
        if not remaining:
            return 0.0, {}, True, False
        shape = self._shape(session)
        speed = self._seconds_per_ocr_page(session)
        workers = max(run.workers, 1)
        seconds: dict[str, float] = {}
        complete, ocr_pending = True, False
        for file_type, files in remaining.items():
            pages_per_file, ocr_share = shape.get(file_type, (None, None))
            if pages_per_file is None:
                complete = False  # nothing like it has been indexed yet
                continue
            ocr_pages = files * pages_per_file * ocr_share
            if ocr_pages <= 0:
                seconds[file_type] = 0.0
                continue
            ocr_pending = True
            if run.tier != self.LOCAL and run.tier != "hybrid":
                continue  # a remote tier reads them: see `_remote`
            per_page = speed.get(file_type)
            if per_page is None:
                complete = False
                continue
            seconds[file_type] = ocr_pages * per_page / workers
        return sum(seconds.values()), seconds, complete, ocr_pending and run.tier != self.LOCAL

    def _remaining(self, session: Session, run: _IndexRun) -> dict[str, int]:
        """The files the run has yet to do, by file type: its total less what it has done, taken
        from the files waiting under its target."""
        left = max(run.total_files - run.processed_files, 0)
        if not left:
            return {}
        statement = select(_DocumentIndex.file_path).where(
            _DocumentIndex.status.in_(
                (FileStatus.PENDING, FileStatus.MODIFIED, FileStatus.PROCESSING)
            ),
            _DocumentIndex.removed_at.is_(None),
        )
        if run.file_path is not None:
            statement = statement.where(_DocumentIndex.file_path == run.file_path)
        elif run.source_id is not None:
            statement = statement.where(_DocumentIndex.source_id == run.source_id)
        counts: dict[str, int] = defaultdict(int)
        for path in session.scalars(statement):
            spec = self.catalog.for_path(path)
            if spec is not None:
                counts[spec.id] += 1
        total = sum(counts.values())
        if total > left:  # some of them are not in this run: keep the share, not the surplus
            scale = left / total
            return {t: max(round(n * scale), 1) for t, n in counts.items()}
        return dict(counts)

    def _shape(self, session: Session) -> dict[str, tuple[float, float]]:
        """For each file type, the pages a file has and the share of them that needed OCR, from the
        files indexed most recently."""
        recent = (
            select(_DocumentIndex.id)
            .where(
                _DocumentIndex.status == FileStatus.INDEXED, _DocumentIndex.document_id.is_not(None)
            )
            .order_by(_DocumentIndex.indexed_at.desc())
            .limit(self.SAMPLE_FILES)
        )
        rows = session.execute(
            select(_DocumentIndex.id, _DocumentIndex.file_path, _PdfPage.source)
            .join(_PdfPage, _PdfPage.document_id == _DocumentIndex.document_id)
            .where(_DocumentIndex.id.in_(recent))
        )
        files: dict[str, set[int]] = defaultdict(set)
        pages: dict[str, int] = defaultdict(int)
        ocr: dict[str, int] = defaultdict(int)
        for file_id, path, source in rows:
            spec = self.catalog.for_path(path)
            if spec is None:
                continue
            files[spec.id].add(file_id)
            pages[spec.id] += 1
            ocr[spec.id] += 0 if source is _PageSource.NATIVE else 1
        return {t: (pages[t] / len(files[t]), ocr[t] / pages[t]) for t in files}

    def _seconds_per_ocr_page(self, session: Session) -> dict[str, float]:
        """Seconds one OCR pass of a page took here, by file type: the last `WINDOW_DAYS` days, or
        all time for a type with nothing in them."""
        since = (datetime.now(UTC) - timedelta(days=self.WINDOW_DAYS)).date().isoformat()

        def averages(recent_only: bool) -> dict[str, float]:
            statement = (
                select(
                    _UsageDaily.file_type,
                    func.sum(_UsageDaily.duration_ms),
                    func.sum(_UsageDaily.passes),
                )
                .where(
                    _UsageDaily.phase != "",
                    _UsageDaily.duration_ms > 0,
                    _UsageDaily.passes > 0,
                )
                .group_by(_UsageDaily.file_type)
            )
            if recent_only:
                statement = statement.where(_UsageDaily.day >= since)
            return {t: ms / 1000 / passes for t, ms, passes in session.execute(statement) if passes}

        everything = averages(False)
        return {**everything, **averages(True)}

    # ----- remote tiers -----------------------------------------------------------------------

    def _remote(self, session: Session, run: _IndexRun, to_send: bool) -> tuple[float, bool]:
        """Time for the jobs still out to come back (they run side by side, so the slowest), plus
        one more batch if the run still has pages to send. `to_send` is whether it has."""
        open_jobs = list(
            session.scalars(
                select(_RemoteJob).where(
                    _RemoteJob.status == RemoteJobStatus.SUBMITTED,
                    _RemoteJob.run_id == run.id,
                )
            )
        )
        if not open_jobs and not to_send:
            return 0.0, True
        turnaround = self._turnaround(session)
        now = datetime.now(UTC)
        longest, complete = 0.0, True
        for job in open_jobs:
            average = turnaround.get(job.tier)
            if average is None:
                complete = False
                continue
            age = (now - datetime.fromisoformat(job.submitted_at)).total_seconds()
            longest = max(longest, average - age, 0.0)
        if to_send:
            tiers = {run.tier} if run.tier != self.LOCAL else set()
            tiers = tiers - {"hybrid"} or set(turnaround)
            known = [turnaround[t] for t in tiers if t in turnaround]
            if known:
                longest += max(known)
            else:
                complete = False
        return longest, complete

    def _turnaround(self, session: Session) -> dict[str, float]:
        """Seconds a batch took from submitted to completed, per tier: the last `WINDOW_DAYS`
        days, or all time for a tier with nothing in them."""
        since = (datetime.now(UTC) - timedelta(days=self.WINDOW_DAYS)).isoformat()

        def averages(recent_only: bool) -> dict[str, float]:
            statement = select(
                _RemoteJob.tier, _RemoteJob.submitted_at, _RemoteJob.completed_at
            ).where(
                _RemoteJob.status == RemoteJobStatus.COMPLETED,
                _RemoteJob.completed_at.is_not(None),
            )
            if recent_only:
                statement = statement.where(_RemoteJob.submitted_at >= since)
            took: dict[str, list[float]] = defaultdict(list)
            for tier, submitted, completed in session.execute(statement):
                seconds = (
                    datetime.fromisoformat(completed) - datetime.fromisoformat(submitted)
                ).total_seconds()
                if seconds >= 0:
                    took[tier].append(seconds)
            return {t: sum(v) / len(v) for t, v in took.items()}

        return {**averages(False), **averages(True)}

    @staticmethod
    def is_active(run: _IndexRun) -> bool:
        """Whether the run is going: marked running, and its process is still there."""
        from vethuq._indexing.runs import _Runs  # noqa: PLC0415 - avoids an import cycle

        return run.status is IndexRunStatus.RUNNING and _Runs._alive(run)
