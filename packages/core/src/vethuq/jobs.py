"""Index requests that wait for a worker: `client.index.queue`.

`submit()` writes a request; a worker (the background service, or anything that calls
`run_next()`) takes the oldest one and runs it with the same `index.run(...)` a person would call,
so every setting, `status()`, `pause()`, `stop()` and the add-ons that act on a run apply to it
unchanged. The worker announces itself with a small marker file in the data folder, which is how
`service_running()` tells index commands that their work will be taken.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as _time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from sqlalchemy import select, update

from vethuq._db import _Database, _IndexJob
from vethuq._errors import _IndexAlreadyRunningError, _IndexJobNotFoundError, _IndexJobStateError
from vethuq._paths import _Paths
from vethuq.enums import IndexJobStatus, IndexRunStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from vethuq.index import Index

MODES = ("run", "restart", "reindex", "file")
_logger = __import__("logging").getLogger("vethuq.indexing")


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _next_reset(after: str | None) -> datetime:
    """The next 00:00 UTC after `after` (an ISO stamp), when credits come back."""
    try:
        moment = datetime.fromisoformat(after) if after else datetime.now(UTC)
    except ValueError:
        moment = datetime.now(UTC)
    return datetime.combine(moment.astimezone(UTC).date() + timedelta(days=1), _time.min, UTC)


@dataclass(frozen=True)
class IndexJob:
    """A request to index."""

    id: int
    target: str | None  # a source id or path, or a file; None means every source
    mode: str  # run, restart, reindex or file
    status: IndexJobStatus
    languages: tuple[str, ...]
    workers: str | None
    tier: str | None
    wait: bool | None
    timeout: float | None
    error: str | None
    pid: int | None  # the worker that took it
    run_id: int | None  # the index run it made
    requested_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def open(self) -> bool:
        """Still waiting or running."""
        return self.status in (IndexJobStatus.QUEUED, IndexJobStatus.RUNNING)

    @property
    def resume_at(self) -> str | None:
        """When a request waiting for credits is taken up again (the next 00:00 UTC), else None."""
        if self.status is not IndexJobStatus.WAITING_CREDITS:
            return None
        return _next_reset(self.finished_at).isoformat()

    @property
    def reason(self) -> str | None:
        """Why the request is not moving, in words: waiting for credits, or running remotely."""
        if self.status is IndexJobStatus.WAITING_CREDITS:
            return f"Waiting for credits until {self.resume_at}"
        return None

    @classmethod
    def _from_model(cls, row: _IndexJob) -> IndexJob:
        return cls(
            id=row.id,
            target=row.target,
            mode=row.mode,
            status=IndexJobStatus(row.status),
            languages=tuple(json.loads(row.languages)) if row.languages else (),
            workers=row.workers,
            tier=row.tier,
            wait=row.wait,
            timeout=row.timeout,
            error=row.error,
            pid=row.pid,
            run_id=row.run_id,
            requested_at=row.requested_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        data["languages"] = list(self.languages)
        data["open"] = self.open
        data["resume_at"] = self.resume_at
        data["reason"] = self.reason
        return data

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class IndexQueue:
    """Requests to index that wait for a worker.

    Not created directly: use `VethuQ().index.queue`.
    """

    MARKER = "service.json"

    def __init__(self, database: _Database, index: Index) -> None:
        self._database = database
        self._index = index

    # ----- asking -----------------------------------------------------------------------------

    def submit(
        self,
        target: int | str | Path | None = None,
        *,
        mode: str = "run",
        workers: int | str | None = None,
        tier: str | None = None,
        wait: bool | None = None,
        timeout: float | None = None,
        languages: str | Sequence[str] | None = None,
    ) -> IndexJob:
        """Ask for indexing to be done by a worker. `mode` is `run`, `restart`, `reindex` or
        `file`, as for `index.run`, `restart`, `reindex` and `reindex_file`; the last two need a
        `target`. Nothing is checked until a worker runs it, so a wrong source fails the job."""
        if mode not in MODES:
            raise ValueError(f"mode is one of {', '.join(MODES)}, not {mode!r}.")
        if mode in ("reindex", "file") and target is None:
            raise ValueError(f"mode {mode!r} needs a target.")
        if isinstance(languages, str):
            languages = [languages]
        row = _IndexJob(
            target=None if target is None else str(target),
            mode=mode,
            languages=json.dumps(list(languages)) if languages else None,
            workers=None if workers is None else str(workers),
            tier=tier,
            wait=wait,
            timeout=timeout,
            status=IndexJobStatus.QUEUED.value,
            requested_at=_stamp(),
        )
        with self._database.session() as session:
            session.add(row)
            session.flush()
            return IndexJob._from_model(row)

    def list(
        self, status: IndexJobStatus | str | None = None, limit: int | None = None
    ) -> list[IndexJob]:
        """Requests, newest first; only those with this `status` if given."""
        query = select(_IndexJob).order_by(_IndexJob.id.desc())
        if status is not None:
            query = query.where(_IndexJob.status == IndexJobStatus(status).value)
        if limit is not None:
            query = query.limit(limit)
        with self._database.session() as session:
            return [IndexJob._from_model(r) for r in session.scalars(query)]

    def get(self, job_id: int) -> IndexJob:
        """One request. Raises `IndexJobNotFoundError`."""
        with self._database.session() as session:
            row = session.get(_IndexJob, job_id)
            if row is None:
                raise _IndexJobNotFoundError(
                    f"There is no index request {job_id}.", "See index.queue.list()."
                )
            return IndexJob._from_model(row)

    def cancel(self, job_id: int) -> IndexJob:
        """Take a waiting request out. Raises `IndexJobStateError` once a worker has it (stop
        its run with `index.stop()`)."""
        with self._database.session() as session:
            row = session.get(_IndexJob, job_id)
            if row is None:
                raise _IndexJobNotFoundError(
                    f"There is no index request {job_id}.", "See index.queue.list()."
                )
            if row.status != IndexJobStatus.QUEUED.value:
                raise _IndexJobStateError(
                    f"Request {job_id} is {row.status}, so it can't be cancelled.",
                    "Only a waiting request can be; stop a running one with index.stop().",
                )
            row.status = IndexJobStatus.CANCELLED.value
            row.finished_at = _stamp()
            session.flush()
            return IndexJob._from_model(row)

    def queued(self) -> int:
        """How many requests are waiting."""
        return len(self.list(IndexJobStatus.QUEUED))

    # ----- working ----------------------------------------------------------------------------

    def reconcile(self) -> int:
        """Put back the requests a worker took and then died on (its process is gone). Returns how
        many."""
        count = 0
        with self._database.session() as session:
            for row in session.scalars(
                select(_IndexJob).where(_IndexJob.status == IndexJobStatus.RUNNING.value)
            ):
                if row.pid is None or not psutil.pid_exists(row.pid):
                    row.status, row.pid, row.started_at = IndexJobStatus.QUEUED.value, None, None
                    count += 1
        return count

    def resume_waiting(self) -> int:
        """Queue the requests that were waiting for credits once the reset has passed. They are
        kept in the database, so this also works after the service was restarted. A resumed
        request carries on (`run`): what was already read is not read, or paid for, again."""
        now, count = datetime.now(UTC), 0
        with self._database.session() as session:
            for row in session.scalars(
                select(_IndexJob).where(_IndexJob.status == IndexJobStatus.WAITING_CREDITS.value)
            ):
                if _next_reset(row.finished_at) <= now:
                    row.status, row.mode = IndexJobStatus.QUEUED.value, "run"
                    row.pid, row.started_at, row.finished_at = None, None, None
                    count += 1
        return count

    def claim_next(self, pid: int | None = None) -> IndexJob | None:
        """Take the oldest waiting request for this worker (`pid`, default this process), or None.
        Two workers never get the same one."""
        self.reconcile()
        self.resume_waiting()
        pid = os.getpid() if pid is None else pid
        while True:
            with self._database.session() as session:
                job_id = session.scalar(
                    select(_IndexJob.id)
                    .where(_IndexJob.status == IndexJobStatus.QUEUED.value)
                    .order_by(_IndexJob.id)
                    .limit(1)
                )
                if job_id is None:
                    return None
                taken = session.execute(
                    update(_IndexJob)
                    .where(_IndexJob.id == job_id, _IndexJob.status == IndexJobStatus.QUEUED.value)
                    .values(status=IndexJobStatus.RUNNING.value, pid=pid, started_at=_stamp())
                ).rowcount
                if taken == 1:
                    return IndexJob._from_model(session.get(_IndexJob, job_id))
            # another worker was quicker: look again

    def finish(
        self,
        job_id: int,
        status: IndexJobStatus | str,
        *,
        run_id: int | None = None,
        error: str | None = None,
    ) -> IndexJob:
        """Close a request a worker took."""
        with self._database.session() as session:
            row = session.get(_IndexJob, job_id)
            if row is None:
                raise _IndexJobNotFoundError(
                    f"There is no index request {job_id}.", "See index.queue.list()."
                )
            row.status = IndexJobStatus(status).value
            row.run_id, row.error, row.finished_at = run_id, error, _stamp()
            session.flush()
            return IndexJob._from_model(row)

    def put_back(self, job_id: int) -> None:
        """Hand a taken request back to the queue (the worker could not run it now)."""
        with self._database.session() as session:
            row = session.get(_IndexJob, job_id)
            if row is not None:
                row.status, row.pid, row.started_at = IndexJobStatus.QUEUED.value, None, None

    def run_next(self, pid: int | None = None) -> IndexJob | None:
        """Take the oldest waiting request, run it, and return it finished; None when nothing is
        waiting, or when a run is already going (the request stays waiting)."""
        job = self.claim_next(pid)
        if job is None:
            return None
        target: int | str | None = job.target
        if target is not None and target.isdigit():
            target = int(target)
        options = {
            "workers": int(job.workers) if job.workers and job.workers.isdigit() else job.workers,
            "tier": job.tier,
            "wait": job.wait,
            "timeout": job.timeout,
            "languages": list(job.languages) or None,
        }
        try:
            if job.mode == "run":
                run = self._index.run(target, **options)
            elif job.mode == "restart":
                run = self._index.restart(target, **options)
            elif job.mode == "reindex":
                run = self._index.reindex(target, **options)  # type: ignore[arg-type]
            else:
                run = self._index.reindex_file(target, **options)  # type: ignore[arg-type]
        except _IndexAlreadyRunningError:
            self.put_back(job.id)
            return None
        except Exception as exc:  # noqa: BLE001 - a bad request fails its job, not the worker
            _logger.warning("Index request %d failed: %s", job.id, exc)
            return self.finish(job.id, IndexJobStatus.FAILED, error=str(exc) or type(exc).__name__)
        if run.status is IndexRunStatus.STOPPED:
            return self.finish(job.id, IndexJobStatus.CANCELLED, run_id=run.id, error=run.error)
        if run.status is IndexRunStatus.FAILED:
            return self.finish(job.id, IndexJobStatus.FAILED, run_id=run.id, error=run.error)
        if run.status is IndexRunStatus.WAITING_CREDITS:
            return self.finish(job.id, IndexJobStatus.WAITING_CREDITS, run_id=run.id)
        return self.finish(job.id, IndexJobStatus.COMPLETED, run_id=run.id)

    # ----- the service marker -------------------------------------------------------------------

    def _marker(self) -> Path:
        return _Paths.run_dir(self._database.db_path) / self.MARKER

    def control_file(self) -> Path:
        """The file a service watches for `pause` and `run` (written by the service commands)."""
        return _Paths.run_dir(self._database.db_path) / "service.control"

    def announce_service(self, pid: int | None = None) -> None:
        """A worker says it is serving this data folder (it calls this when it starts)."""
        self._marker().write_text(
            json.dumps({"pid": os.getpid() if pid is None else pid, "started_at": _stamp()}),
            encoding="utf-8",
        )

    def clear_service(self) -> None:
        """The worker says it has stopped."""
        self._marker().unlink(missing_ok=True)

    def service_info(self) -> dict[str, object] | None:
        """What the running worker announced (`pid`, `started_at`), or None when none is running
        (a marker left by a worker that died is ignored)."""
        marker = self._marker()
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        pid = data.get("pid")
        if not isinstance(pid, int) or not psutil.pid_exists(pid):
            return None
        return data

    def service_running(self) -> bool:
        """Whether a worker is serving this data folder, so submitted requests will be taken."""
        return self.service_info() is not None

    def wait(self, job_id: int, timeout: float | None = None, poll: float = 1.0) -> IndexJob:
        """Wait until a request is over (or `timeout` seconds pass) and return it."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            job = self.get(job_id)
            if not job.open or (deadline is not None and time.monotonic() >= deadline):
                return job
            time.sleep(poll)
