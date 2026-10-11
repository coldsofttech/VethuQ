"""Indexing: reading sources into searchable pages: `VethuQ().index`.

    run = client.index.run()                 # every source
    run = client.index.run("~/docs")         # one source
    run = client.index.run("~/docs/a.pdf")   # one file in a source

A run reads each file's text layer first, and runs OCR only on the pages and images that need it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from vethuq._db import _Database, _IndexRun, _RemoteJob
from vethuq._errors import _IndexNotRunningError
from vethuq._indexing import _Indexer, _Runs
from vethuq._indexing.eta import _Eta, _EtaResult
from vethuq._metrics import _Metrics
from vethuq.enums import IndexRunSortBy, IndexRunStatus, RemoteJobStatus, SortOrder

__all__ = [
    "Index",
    "IndexEta",
    "IndexRun",
    "IndexRunSortBy",
    "IndexRunStatus",
    "RemoteJob",
    "RemoteJobStatus",
    "SortOrder",
    "IndexStatus",
]


@dataclass(frozen=True)
class IndexEta:
    """How long an index run has left, estimated from what earlier runs took here.

    Pages read on this computer are sized from the seconds an OCR page took (per file type, over
    the last 30 days, else all time) and from how many pages, and how many that needed OCR, files of
    that type had; native text costs nothing. Pages away on a remote tier (GitHub) are sized from
    how long its earlier jobs took. Nothing is timed during the run, so an estimate exists before
    the first file is done. It is a guess: `complete` says whether every part of the work had
    history to go on.
    """

    seconds: int  # the best estimate of the time left; 0 when nothing is left
    local_seconds: int  # of it, the pages read on this computer
    remote_seconds: int  # of it, waiting for jobs on a remote tier
    complete: bool  # False when part of the work has no history; `seconds` then leaves it out
    by_file_type: dict[str, int] = field(default_factory=dict)  # the quick phase's, per file type
    by_phase: dict[str, int] = field(default_factory=dict)  # `local_seconds`, per OCR phase

    @classmethod
    def _from_result(cls, result: _EtaResult) -> IndexEta:
        return cls(
            seconds=round(result.seconds),
            local_seconds=round(result.local_seconds),
            remote_seconds=round(result.remote_seconds),
            complete=result.complete,
            by_file_type={t: round(s) for t, s in sorted(result.by_file_type.items())},
            by_phase={p: round(s) for p, s in result.by_phase.items()},
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "seconds": self.seconds,
            "local_seconds": self.local_seconds,
            "remote_seconds": self.remote_seconds,
            "complete": self.complete,
            "by_file_type": dict(self.by_file_type),
            "by_phase": dict(self.by_phase),
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


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
    tier: str  # the processing tier it ran with
    mode: str  # how it was asked for: run, restart, reindex or file
    started_at: str  # UTC, ISO 8601
    completed_at: str | None
    error: str | None
    # The time left when this was returned by `Index.run()` (the pages still away on a remote tier);
    # None in `get()` and `history()`.
    eta: IndexEta | None = field(default=None, compare=False)

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
            tier=model.tier,
            mode=model.mode,
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
            "tier": self.tier,
            "mode": self.mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "eta": self.eta.to_dict() if self.eta is not None else None,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class IndexStatus:
    """Where the latest index run is, and how long it has left."""

    run: IndexRun  # the latest run (its counts are live while it goes)
    active: bool  # the run is going now (here, or in another process)
    remote_jobs_open: int  # batches still out on a remote tier
    eta: IndexEta
    # What the caller asked of the run: `run`, `pause` or `stop`.
    control: str = "run"
    phase: str = ""  # the OCR phase it is on (`quick`, `moderate`, `deep`); empty when over
    current_files: tuple[str, ...] = ()  # the files being read right now
    workers_active: int = 0
    deepened_pages: int = 0  # pages the deeper phases have read in this run
    unsupported_files: int = 0  # files under the run's target that no add-on reads
    heartbeat_at: str | None = None  # when the running run last said it was still going (UTC)
    # The run's process is alive but has been quiet for two minutes or more: it is hung. Stop it
    # from the outside (kill the process), then `clear_stale()`.
    stalled: bool = False

    @property
    def paused(self) -> bool:
        """The run is waiting to be resumed."""
        return self.active and self.control == "pause"

    @property
    def stopping(self) -> bool:
        """A stop was asked for and the run is finishing the file it is on."""
        return self.active and self.control == "stop"

    @property
    def finished(self) -> bool:
        """Nothing is going on any more: the run is over and no remote job is out."""
        return not self.active and self.remote_jobs_open == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "run": self.run.to_dict(),
            "active": self.active,
            "remote_jobs_open": self.remote_jobs_open,
            "finished": self.finished,
            "paused": self.paused,
            "stopping": self.stopping,
            "phase": self.phase,
            "current_files": list(self.current_files),
            "workers_active": self.workers_active,
            "deepened_pages": self.deepened_pages,
            "unsupported_files": self.unsupported_files,
            "heartbeat_at": self.heartbeat_at,
            "stalled": self.stalled,
            "eta": self.eta.to_dict(),
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class RemoteJob:
    """A batch of images sent to a remote processing tier."""

    id: int
    run_id: int | None  # the run that sent it
    tier: str
    status: RemoteJobStatus
    images: int  # how many images it holds
    size_bytes: int
    credits: float  # what it cost (given back if it fails or expires)
    submitted_at: str  # UTC, ISO 8601
    completed_at: str | None
    error: str | None

    @classmethod
    def _from_model(cls, model: _RemoteJob) -> RemoteJob:
        return cls(
            id=model.id,
            run_id=model.run_id,
            tier=model.tier,
            status=model.status,
            images=model.images,
            size_bytes=model.size_bytes,
            credits=model.credits_milli / 1000,
            submitted_at=model.submitted_at,
            completed_at=model.completed_at,
            error=model.error,
        )

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        return data

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
        self,
        target: int | str | Path | None = None,
        *,
        workers: int | str | None = None,
        tier: str | None = None,
        wait: bool | None = None,
        timeout: float | None = None,
        languages: str | Sequence[str] | None = None,
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

        `languages` (a language id, or a list: `["en", "te"]`) reads the files in those languages
        for this run, instead of each source's own languages or the default languages setting.
        With one, that is the language. With several, the first (English, unless it is not among
        them) reads each file, and the others read it as well only if that read was doubted.
        `LanguageUnavailableError` if one can't be used.

        `tier` is the processing tier that reads the pages needing OCR (a `ProcessingTier` or its
        id); left out, the default from `tiers` applies. `wait` and `timeout` (minutes) are for
        tiers whose work finishes later; the local tier ignores them.

        Raises `TierUnavailableError` if the tier isn't known or can't be used,
        `IndexAlreadyRunningError` if a run is going, `SourceNotFoundError` if `target`
        isn't a source or a file in one, and `SourcePathError` if the source is gone from disk.
        """
        return self._start("run", target, workers, tier, wait, timeout, languages)

    def restart(
        self,
        target: int | str | Path | None = None,
        *,
        workers: int | str | None = None,
        tier: str | None = None,
        wait: bool | None = None,
        timeout: float | None = None,
        languages: str | Sequence[str] | None = None,
    ) -> IndexRun:
        """Try again only the files that failed last time. New and already indexed files are left
        alone. Same arguments, errors and result as `run`."""
        return self._start("restart", target, workers, tier, wait, timeout, languages)

    def reindex(
        self,
        target: int | str | Path,
        *,
        workers: int | str | None = None,
        tier: str | None = None,
        wait: bool | None = None,
        timeout: float | None = None,
        languages: str | Sequence[str] | None = None,
    ) -> IndexRun:
        """Read every file under `target` (a source, or a file in one) again, whether or not it
        was indexed: the way to use a new OCR phase or add-on, or new models, on what is already
        indexed. Each file's old pages stay searchable until the file has been read again, and its
        status stays `INDEXED`; a file that fails to read again keeps the pages it had (see its
        `index.error`). It costs credits again. Same arguments, errors and result as `run`."""
        if target is None or isinstance(target, bool):
            raise TypeError("reindex needs a source or a file; use run() for new files.")
        return self._start("reindex", target, workers, tier, wait, timeout, languages)

    def reindex_file(
        self,
        file: int | str | Path,
        *,
        workers: int | str | None = None,
        tier: str | None = None,
        wait: bool | None = None,
        timeout: float | None = None,
        languages: str | Sequence[str] | None = None,
    ) -> IndexRun:
        """Read one file again: a path, or a document id (see `list_files`). Like `reindex`, the
        old pages stay searchable until it is done. Raises `FileNotTrackedError` if VethuQ doesn't
        track the file; otherwise as `run`."""
        path = self._indexer.file_target(file)
        return self._start("file", path, workers, tier, wait, timeout, languages)

    @staticmethod
    def _languages(languages: str | Sequence[str] | None) -> list[str] | None:
        if languages is None:
            return None
        if isinstance(languages, str):
            languages = [part for part in languages.replace(",", " ").split() if part]
        elif isinstance(languages, bool) or not isinstance(languages, Sequence):
            raise TypeError('languages is a language id or a list of them, e.g. ["en", "te"]')
        return [str(code) for code in languages] or None

    def _start(self, mode, target, workers, tier, wait, timeout, languages=None) -> IndexRun:
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0
        ):
            raise ValueError("timeout must be a number of minutes above 0.")
        if wait is not None and not isinstance(wait, bool):
            raise TypeError("wait is True, False or None.")
        run_id = self._indexer.run(
            target, workers, tier, wait, timeout, mode, self._languages(languages)
        )
        self._metrics.send()  # if you opted in; at most once a day; never raises
        return replace(self.get(run_id), eta=self._eta(run_id))

    def clear_stale(self) -> int:
        """Fail the runs left behind by a process that ended, and put their files back to be
        read. It is what a new run does by itself unless the stale-lock setting is `disable`.
        Returns how many runs were cleared. A run that is really going is never touched."""
        with self._database.session() as session:
            return _Runs.clear_stale(session)

    # ----- control ----------------------------------------------------------------------------

    def _ask(self, state: str, allowed: tuple[str, ...]) -> int:
        with self._database.session() as session:
            _Runs.recover(session)
            run = _Runs.going(session)
            if run is None:
                raise _IndexNotRunningError(
                    "No index run is going.", "Start one with run(), or see status()."
                )
            if run.control not in allowed:
                return run.id
            run.control = state
            return run.id

    def pause(self) -> None:
        """Pause the run that is going. It stops taking new work at the next checkpoint (between
        files, pages and angle passes) and waits to be resumed. Works from another thread or
        process. Raises `IndexNotRunningError` if no run is going."""
        self._ask("pause", ("run",))

    def resume(self) -> None:
        """Carry on a paused run. Raises `IndexNotRunningError` if no run is going."""
        self._ask("run", ("pause",))

    def stop(self, *, wait: bool = True, timeout: float | None = None) -> IndexStatus | None:
        """Stop the run that is going, after the file it is on: that file waits for the next run
        with the pages it already has, and the run ends as `STOPPED`. With `wait` (the default)
        this returns once the run is over, or after `timeout` minutes. Pages already sent to a
        remote tier still come back. Raises `IndexNotRunningError` if no run is going."""
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0
        ):
            raise ValueError("timeout must be a number of minutes above 0.")
        run_id = self._ask("stop", ("run", "pause"))
        if not wait:
            return self._status()
        deadline = time.monotonic() + timeout * 60 if timeout is not None else None
        while True:
            with self._database.session() as session:
                _Runs.recover(session)
                running = _Runs.going(session)
            if running is None or running.id != run_id:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        return self._status()

    def _eta(self, run_id: int) -> IndexEta:
        with self._database.session() as session:
            model = _Runs.get(session, run_id)
            estimate = _Eta(self._indexer.file_types, self._indexer.deepener).estimate(
                session, model, _Eta.is_active(model)
            )
        return IndexEta._from_result(estimate)

    def status(self, *, wait: bool = False, timeout: float | None = None) -> IndexStatus | None:
        """Where the latest index run is: its counts, whether it is going, the remote jobs still
        out, and the time left (`eta`). None if no run has ever started.

        It reads the database, so it works while `run()` is going in another thread or process.
        With `wait=True` it blocks until nothing is going on any more (the run is over, and so is
        every remote job it sent, collecting the results as they come back), then returns the
        final status. `timeout` (minutes) bounds the wait: the time is up, you get the status as it
        is then. Left out, a run is waited for as long as it goes and remote jobs for the
        `settings.tiers` wait time.
        """
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0
        ):
            raise ValueError("timeout must be a number of minutes above 0.")
        if not isinstance(wait, bool):
            raise TypeError("wait is True or False.")
        current = self._status()
        if current is None or not wait:
            return current
        deadline = time.monotonic() + timeout * 60 if timeout is not None else None
        remote_deadline = None
        while not current.finished:
            if deadline is not None and time.monotonic() >= deadline:
                break
            if not current.active:
                # The run is over; what is left is jobs away. Ask about them, for a while.
                if remote_deadline is None:
                    minutes = self._indexer.wait_minutes()
                    remote_deadline = time.monotonic() + minutes * 60
                if time.monotonic() >= remote_deadline:
                    break
                self._indexer.collect(current.run.id, False, None)
            time.sleep(self._indexer.POLL_SECONDS if not current.active else 1.0)
            current = self._status() or current
        return current

    def _status(self) -> IndexStatus | None:
        with self._database.session() as session:
            _Runs.recover(session)  # a run whose process died is failed, not "running"
            latest = _Runs.history(session, limit=1)
            if not latest:
                return None
            model = latest[0]
            active = _Eta.is_active(model)
            estimate = _Eta(self._indexer.file_types, self._indexer.deepener).estimate(
                session, model, active
            )
            return IndexStatus(
                run=IndexRun._from_model(model, _Runs.source_path(session, model)),
                active=active,
                remote_jobs_open=len(self._indexer.remote.open_jobs(session, model.id)),
                eta=IndexEta._from_result(estimate),
                control=model.control if active else "run",
                phase=model.phase if active else "",
                current_files=tuple(json.loads(model.current_files or "[]")) if active else (),
                workers_active=model.workers_active if active else 0,
                deepened_pages=model.deepened_pages,
                unsupported_files=model.unsupported_files,
                heartbeat_at=model.heartbeat_at if active else None,
                stalled=active
                and _Runs.stalled(model, limit=self._indexer.STALE_HEARTBEAT_SECONDS),
            )

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

    def collect(
        self, run_id: int | None = None, *, wait: bool = False, timeout: float | None = None
    ) -> list[RemoteJob]:
        """Ask the remote tiers about the jobs that are still out (of one run, or all of them)
        and take in the results of those that are done. The pages arrive, and files whose pages
        have all arrived become indexed. A job that failed or took too long is given back: its
        pages wait to be sent again by a later run, and its credits are refunded.

        With `wait=True` it keeps asking until no job is out or `timeout` minutes (default:
        `settings.tiers`) pass. Returns the jobs that ended."""
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0
        ):
            raise ValueError("timeout must be a number of minutes above 0.")
        ended = self._indexer.collect(run_id, wait, timeout)
        with self._database.session() as session:
            return [RemoteJob._from_model(session.get(_RemoteJob, job_id)) for job_id in ended]

    def jobs(
        self,
        status: RemoteJobStatus | str | None = None,
        run_id: int | None = None,
        tier: str | None = None,
        order: SortOrder | str = SortOrder.DESC,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RemoteJob]:
        """The remote jobs, newest first unless `order` says otherwise. `status` keeps one
        `RemoteJobStatus`, `run_id` the jobs a run sent, `tier` those of one tier."""
        from sqlalchemy import select  # noqa: PLC0415

        from vethuq._sources import _Sources  # noqa: PLC0415 - avoids an import cycle

        direction = _Sources._coerce(SortOrder, order, "order")
        statement = select(_RemoteJob)
        if status is not None:
            statement = statement.where(
                _RemoteJob.status == _Sources._coerce(RemoteJobStatus, status, "status")
            )
        if run_id is not None:
            statement = statement.where(_RemoteJob.run_id == run_id)
        if tier is not None:
            statement = statement.where(_RemoteJob.tier == str(tier).strip().lower())
        column = _RemoteJob.id.desc() if direction is SortOrder.DESC else _RemoteJob.id.asc()
        statement = statement.order_by(column)
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        with self._database.session() as session:
            return [RemoteJob._from_model(job) for job in session.scalars(statement)]
