"""Pages whose OCR is done elsewhere: staging them, sending them in jobs, and taking the results
back when the jobs are done."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from vethuq._credits import _Clock, _Credits, _Pricing
from vethuq._db import (
    _Database,
    _DocumentIndex,
    _IndexRun,
    _Language,
    _PdfPage,
    _RemoteJob,
    _RemoteJobPage,
)
from vethuq._db.values import _JobPageState, _PageSource, _PageState
from vethuq._documents import _Documents
from vethuq._indexing.store import _PageStore
from vethuq._ocr import _PageOcr, _PageResult
from vethuq._settings import _ConfidenceSettings, _TierSettings
from vethuq._stats import _PageFact, _Usage
from vethuq._tiers import _Tiers
from vethuq.enums import FileStatus, IndexRunStatus, RemoteJobStatus
from vethuq_addon_api import JobState, OcrRequest, OcrResult

if TYPE_CHECKING:
    from vethuq._indexing.deepening import _Deepener

_logger = logging.getLogger("vethuq.indexing")


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _size(image: object) -> int:
    """About how many bytes an image takes to send."""
    nbytes = getattr(image, "nbytes", None)
    if isinstance(nbytes, int):
        return nbytes
    if isinstance(image, bytes | bytearray):
        return len(image)
    try:
        return Path(str(image)).stat().st_size if isinstance(image, str | Path) else 0
    except OSError:
        return 0


@dataclass
class _Entry:
    request: OcrRequest
    job_page_id: int
    size: int


class _Outbox:
    """Collects the images of staged pages and sends them in jobs of bounded size."""

    def __init__(self, remote: _Remote, tier: str, run_id: int | None) -> None:
        self.remote = remote
        self.tier = tier
        self.run_id = run_id
        self.entries: list[_Entry] = []
        self.bytes = 0
        self.images: set[int] = set()  # the images (by identity) the batch already holds
        self.lock = threading.Lock()
        with remote.database.session() as session:
            self.max_images = _TierSettings.get_max_job_pages(session)
            self.max_bytes = _TierSettings.get_max_job_megabytes(session) * 1024 * 1024

    def add(self, requests: list[OcrRequest], job_page_ids: list[int]) -> None:
        with self.lock:
            for request, job_page_id in zip(requests, job_page_ids, strict=True):
                # One image read at several angles is sent once.
                size = 0 if id(request.image) in self.images else _size(request.image)
                if self.entries and (
                    len(self.entries) >= self.max_images or self.bytes + size > self.max_bytes
                ):
                    self._send()
                self.entries.append(_Entry(request, job_page_id, size))
                self.images.add(id(request.image))
                self.bytes += size

    def flush(self) -> None:
        with self.lock:
            self._send()

    def _send(self) -> None:
        entries, self.entries, self.bytes = self.entries, [], 0
        self.images = set()
        if entries:
            self.remote.submit(self.tier, self.run_id, entries)


class _Remote:
    """Staging, sending, collecting and giving back, for tiers whose work finishes later."""

    EXPIRE_HOURS = 24
    _lock = threading.RLock()

    def __init__(
        self,
        database: _Database,
        tiers: _Tiers,
        credits: _Credits,
        language_of: Callable[[Session, _DocumentIndex], int | None],
        file_type_of: Callable[[str], str],
    ) -> None:
        self.database = database
        self.tiers = tiers
        self.credits = credits
        self.language_of = language_of
        self.file_type_of = file_type_of
        self.deepener: _Deepener | None = None  # set by the indexer: merges deeper phases

    # ----- staging ----------------------------------------------------------------------------

    @staticmethod
    def staged(
        session: Session, document_id: int, language_id: int, phase: str = "quick"
    ) -> set[int]:
        """Pages of a document whose images are paid for and staged or away (in this language and
        OCR phase)."""
        return set(
            session.scalars(
                select(_RemoteJobPage.page_number).where(
                    _RemoteJobPage.document_id == document_id,
                    _RemoteJobPage.language_id == language_id,
                    _RemoteJobPage.phase == phase,
                    _RemoteJobPage.state.in_((_JobPageState.STAGED, _JobPageState.SENT)),
                )
            )
        )

    def stage(
        self,
        session: Session,
        document_id: int,
        language_id: int,
        result: _PageResult,
        run_id: int | None,
        wallet: str,
    ) -> list[int]:
        """Record the images of a pending page, paid for. Returns their ids, in request order."""
        count = max(len(result.requests), 1)
        each, extra = divmod(result.credits_milli, count)
        ids = []
        for index, request in enumerate(result.requests):
            row = _RemoteJobPage(
                document_id=document_id,
                page_number=result.page_number,
                region=index,
                language_id=language_id,
                request_key=request.key,
                state=_JobPageState.STAGED,
                size_factor_milli=round(result.size_factor * 1000),
                credits_milli=each + (extra if index == 0 else 0),
                ledger_ids=",".join(str(i) for i in result.ledger_ids) if index == 0 else "",
                run_id=run_id,
                wallet=wallet,
            )
            session.add(row)
            session.flush()
            ids.append(row.id)
        return ids

    # ----- sending ----------------------------------------------------------------------------

    def submit(self, tier: str, run_id: int | None, entries: list[_Entry]) -> None:
        view = self.tiers.get(tier)
        ids = [e.job_page_id for e in entries]
        try:
            if view is None or view.executor is None or not view.available:
                raise RuntimeError("the tier isn't available")
            handle = view.executor.submit([e.request for e in entries])
        except Exception as exc:  # noqa: BLE001 - a failed send gives the pages back
            _logger.warning("Sending %d image(s) to %s failed: %s", len(entries), tier, exc)
            with self.database.session() as session:
                self._give_back(session, ids, f"sending to {tier} failed")
            return
        with self.database.session() as session:
            wallet = view.wallet
            rows = [session.get(_RemoteJobPage, i) for i in ids]
            job = _RemoteJob(
                run_id=run_id,
                tier=tier,
                wallet=wallet,
                handle=str(handle),
                status=RemoteJobStatus.SUBMITTED,
                images=len(entries),
                size_bytes=sum(e.size for e in entries),
                credits_milli=sum(r.credits_milli for r in rows if r),
                submitted_at=_stamp(),
                updated_at=_stamp(),
            )
            session.add(job)
            session.flush()
            for row in rows:
                if row is not None:
                    row.job_id, row.state = job.id, _JobPageState.SENT
                    session.execute(
                        update(_PdfPage)
                        .where(
                            _PdfPage.document_id == row.document_id,
                            _PdfPage.page_number == row.page_number,
                            _PdfPage.status == _PageState.WAITING,
                        )
                        .values(status=_PageState.DISPATCHED)
                    )

    # ----- giving back ------------------------------------------------------------------------

    def _give_back(self, session: Session, job_page_ids: list[int], note: str) -> None:
        """Refund images that never came back, delete them, and put their pages back to waiting."""
        by_wallet: dict[tuple[str, int | None], list[_RemoteJobPage]] = {}
        for page_id in job_page_ids:
            row = session.get(_RemoteJobPage, page_id)
            if row is not None:
                by_wallet.setdefault((row.wallet, row.run_id), []).append(row)
        for (wallet, run_id), rows in by_wallet.items():
            ledger = [int(i) for r in rows for i in r.ledger_ids.split(",") if i]
            if ledger:
                self.credits.refund(
                    session, wallet, ledger, run_id=run_id,
                    credits_milli=sum(r.credits_milli for r in rows), images=len(rows), note=note,
                )  # fmt: skip
            for row in rows:
                session.execute(
                    update(_PdfPage)
                    .where(
                        _PdfPage.document_id == row.document_id,
                        _PdfPage.page_number == row.page_number,
                        _PdfPage.status == _PageState.DISPATCHED,
                    )
                    .values(status=_PageState.WAITING)
                )
                session.delete(row)
        session.flush()

    def recover(self, session: Session) -> None:
        """Images paid for but never sent (their run died) are refunded and put back."""
        stale = list(
            session.scalars(
                select(_RemoteJobPage.id).where(
                    _RemoteJobPage.job_id.is_(None), _RemoteJobPage.state == _JobPageState.STAGED
                )
            )
        )
        if stale:
            _logger.warning("Giving back %d staged image(s) that were never sent", len(stale))
            self._give_back(session, stale, "the run ended before the images were sent")

    # ----- collecting -------------------------------------------------------------------------

    def open_jobs(self, session: Session, run_id: int | None = None) -> list[_RemoteJob]:
        statement = select(_RemoteJob).where(_RemoteJob.status == RemoteJobStatus.SUBMITTED)
        if run_id is not None:
            statement = statement.where(_RemoteJob.run_id == run_id)
        return list(session.scalars(statement.order_by(_RemoteJob.id)))

    def collect(self, run_id: int | None = None) -> list[int]:
        """Look at every open job (of a run, or all): import the ones that are done, give back
        the ones that failed or took too long. Returns the ids of the jobs that ended."""
        ended: list[int] = []
        with self.database.session() as session:
            jobs = [
                (j.id, j.tier, j.handle, j.submitted_at) for j in self.open_jobs(session, run_id)
            ]
        for job_id, tier, handle, submitted in jobs:
            view = self.tiers.get(tier)
            if view is None or view.executor is None or not view.available:
                continue  # can't ask now; try again later
            try:
                state = view.executor.poll(handle)
                results = view.executor.collect(handle) if state is JobState.DONE else {}
            except Exception as exc:  # noqa: BLE001 - one job never stops the others
                _logger.warning("Asking %s about job %s failed: %s", tier, job_id, exc)
                continue
            with self.database.session() as session:
                job = session.get(_RemoteJob, job_id)
                if job is None or job.status is not RemoteJobStatus.SUBMITTED:
                    continue
                if state is JobState.DONE:
                    self._import(session, job, results)
                elif state is JobState.FAILED:
                    self._end(session, job, RemoteJobStatus.FAILED, "the tier reported a failure")
                elif datetime.fromisoformat(submitted) < datetime.now(UTC) - timedelta(
                    hours=self.EXPIRE_HOURS
                ):
                    try:
                        view.executor.cancel(handle)
                    except Exception:  # noqa: BLE001
                        _logger.debug("Couldn't cancel job %s", job_id)
                    self._end(session, job, RemoteJobStatus.EXPIRED, "it took too long")
                else:
                    job.updated_at = _stamp()
                    continue
                ended.append(job_id)
        return ended

    def _end(self, session: Session, job: _RemoteJob, status: RemoteJobStatus, error: str) -> None:
        pages = list(
            session.scalars(select(_RemoteJobPage.id).where(_RemoteJobPage.job_id == job.id))
        )
        self._give_back(session, pages, f"remote job {job.id}: {error}")
        job.status, job.error = status, error
        job.completed_at = job.updated_at = _stamp()
        self._settle_runs(session, {job.run_id})

    def _import(self, session: Session, job: _RemoteJob, results: dict[str, OcrResult]) -> None:
        rows = list(session.scalars(select(_RemoteJobPage).where(_RemoteJobPage.job_id == job.id)))
        pages: dict[tuple[int, int, int, str], list[_RemoteJobPage]] = {}
        for row in rows:
            key = (row.document_id, row.page_number, row.language_id, row.phase)
            pages.setdefault(key, []).append(row)
        done: list[tuple[int, int]] = []
        missing: list[int] = []
        bands = _ConfidenceSettings.get_bands(session)
        today = _Clock.today(session).isoformat()
        for (document_id, number, language_id, phase), images in pages.items():
            ordered = sorted(images, key=lambda r: (r.region, r.angle))
            answers = [results.get(r.request_key) for r in ordered]
            if any(a is None for a in answers):
                missing += [r.id for r in images]
                continue
            if phase != "quick":  # a deeper phase: its text is merged into the page
                if self.deepener is not None:
                    self.deepener.complete(
                        session, document_id, number, language_id, phase, ordered, answers
                    )
                for image in images:
                    image.state = _JobPageState.DONE
                continue
            self._complete_page(
                session, document_id, number, language_id, images, answers, bands, today
            )
            for image in images:
                image.state = _JobPageState.DONE
            done.append((document_id, language_id))
        if missing:
            self._give_back(session, missing, f"remote job {job.id}: no result for the image")
        job.status = RemoteJobStatus.COMPLETED
        job.completed_at = job.updated_at = _stamp()
        job.error = f"{len(missing)} image(s) came back empty" if missing else None
        session.flush()
        finished_runs = {job.run_id}
        for document_id, language_id in dict.fromkeys(done):
            finished_runs |= self.finalize(session, document_id, language_id)
        self._settle_runs(session, finished_runs)

    def _complete_page(
        self,
        session: Session,
        document_id: int,
        number: int,
        language_id: int,
        images: list[_RemoteJobPage],
        answers: list[OcrResult | None],
        bands: tuple[int, int, int],
        today: str,
    ) -> None:
        page = session.scalars(
            select(_PdfPage).where(
                _PdfPage.document_id == document_id, _PdfPage.page_number == number
            )
        ).first()
        if page is None:
            return
        fresh = page.status is not _PageState.DONE
        result = _PageOcr.combine(
            number,
            page.text if fresh else "",
            fresh and page.source is _PageSource.MIXED,
            [a for a in answers if a is not None],
            0,
            sum(i.size_factor_milli for i in images[:1]) / 1000,
            sum(i.credits_milli for i in images),
        )
        _PageStore.save_page(session, document_id, result, language_id)
        first = session.scalars(
            select(_DocumentIndex).where(_DocumentIndex.document_id == document_id)
        ).first()
        source_id = first.source_id if first else None
        file_type = self.file_type_of(first.file_path) if first else ""
        code = session.scalar(select(_Language.language).where(_Language.id == language_id)) or ""
        _Usage.record_pages(
            session, today, source_id, file_type, code,
            [
                _PageFact(
                    page_source=result.source.value,
                    phase="quick",
                    engine=result.quick.engine if result.quick else "",
                    size_bucket=_Pricing.bucket(result.size_factor),
                    confidence=result.confidence,
                    duration_ms=0,
                    credits_milli=result.credits_milli,
                    passes=1,
                )
            ],
            bands,
        )  # fmt: skip
        run_id = images[0].run_id
        if run_id is not None:
            session.execute(
                update(_IndexRun)
                .where(_IndexRun.id == run_id)
                .values(processed_pages=_IndexRun.processed_pages + 1)
            )

    def finalize(self, session: Session, document_id: int, language_id: int) -> set[int | None]:
        """If every page of the document is now read, finish the pass and the files that were
        waiting for it. Returns the runs those files belonged to."""
        if _PageStore.waiting(session, document_id) or self.staged(
            session, document_id, language_id
        ):
            return set()
        if _PageStore.pass_row(session, document_id, language_id) is None:
            return set()
        _PageStore.finish_pass(session, document_id, language_id)
        runs: set[int | None] = set()
        rows = session.scalars(
            select(_DocumentIndex).where(
                _DocumentIndex.document_id == document_id,
                _DocumentIndex.status == FileStatus.PROCESSING,
            )
        ).all()
        for row in rows:
            if self.language_of(session, row) != language_id or not row.sha256:
                continue
            _Documents.finish(session, row, row.sha256)
            origin = session.scalars(
                select(_RemoteJobPage.run_id).where(_RemoteJobPage.document_id == document_id)
            ).first()
            runs.add(origin)
            if origin is not None:
                session.execute(
                    update(_IndexRun)
                    .where(_IndexRun.id == origin)
                    .values(processed_files=_IndexRun.processed_files + 1)
                )
        return runs

    def _settle_runs(self, session: Session, run_ids: set[int | None]) -> None:
        """A run that was waiting on remote work is complete once that work has all arrived."""
        for run_id in run_ids:
            if run_id is None:
                continue
            run = session.get(_IndexRun, run_id)
            if run is None or run.status is not IndexRunStatus.WAITING_REMOTE:
                continue
            still_open = session.scalar(
                select(func.count())
                .select_from(_RemoteJob)
                .where(_RemoteJob.run_id == run_id, _RemoteJob.status == RemoteJobStatus.SUBMITTED)
            )
            if not still_open:
                run.status, run.error = IndexRunStatus.COMPLETED, None
                run.completed_at = _stamp()
        session.flush()
