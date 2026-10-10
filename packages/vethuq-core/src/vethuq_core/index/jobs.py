"""Every index request, queued or run: the `index_jobs` table.

A request is a row. The background service claims queued rows; a one-off request launches its own
worker for its row straight away. Whichever worker runs a job records its pid and its
`index_runs` row (`attach_run`) and closes the job when the run ends, so `index queue list` shows
what is waiting, running and finished however each run was started.
"""

from __future__ import annotations

import builtins
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from vethuq_core.storage import Row, Storage, default_db_path, open_storage


@dataclass
class IndexJob:
    id: int
    target: str | None
    mode: str  # "run" | "restart"
    languages: str | None
    status: str  # "queued" | "running" | "completed" | "failed" | "cancelled"
    error: str | None
    pid: int | None
    run_id: int | None
    requested_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def restart(self) -> bool:
        return self.mode == "restart"

    @property
    def is_open(self) -> bool:
        """Still waiting or running."""
        return self.status in ("queued", "running")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Row) -> IndexJob:
        return cls(
            id=row["id"],
            target=row["target"],
            mode=row["mode"],
            languages=row["languages"],
            status=row["status"],
            error=row["error"],
            pid=row["pid"],
            run_id=row["run_id"],
            requested_at=row["requested_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


class IndexJobs:
    """Job operations. Each call opens its own short-lived connection, so the CLI, the UI, the
    service and the workers can all use the table at once without sharing a handle."""

    KEEP_FINISHED = 100
    DIED_MESSAGE = "The index worker exited before finishing this job."
    _RUN_OUTCOMES = {"completed": "completed", "stopped": "cancelled", "failed": "failed"}

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def job_status_for_run(run_status: str) -> str:
        """The job status that matches how its run ended."""
        return IndexJobs._RUN_OUTCOMES.get(run_status, "failed")

    @staticmethod
    def enqueue(
        target: str | None,
        *,
        restart: bool = False,
        languages: str | None = None,
        coalesce: bool = True,
        db_path: Path | None = None,
    ) -> IndexJob:
        """Add a job. With `coalesce`, an identical job already waiting is reused rather than
        added again, so something that asks repeatedly (the app's periodic rescan) can't pile
        jobs up."""
        storage = open_storage(db_path or default_db_path())
        try:
            mode = "restart" if restart else "run"
            if coalesce:
                for row in storage.list_index_jobs(("queued",), 500):
                    if (row["target"], row["mode"], row["languages"]) == (target, mode, languages):
                        return IndexJob.from_row(row)
            job_id = storage.enqueue_index_job(target, mode, languages, IndexJobs._now())
            storage.commit()
            return IndexJobs._get(storage, job_id)
        finally:
            storage.close()

    @staticmethod
    def _get(storage: Storage, job_id: int) -> IndexJob:
        row = storage.get_index_job(job_id)
        if row is None:
            raise LookupError(f"index job {job_id} not found")
        return IndexJob.from_row(row)

    @staticmethod
    def get(job_id: int, db_path: Path | None = None) -> IndexJob | None:
        IndexJobs.reconcile(db_path)
        storage = open_storage(db_path or default_db_path())
        try:
            row = storage.get_index_job(job_id)
            return IndexJob.from_row(row) if row is not None else None
        finally:
            storage.close()

    @staticmethod
    def list(
        statuses: tuple[str, ...] | None = None,
        *,
        limit: int = 20,
        db_path: Path | None = None,
    ) -> list[IndexJob]:
        """Jobs in the given statuses (all if None): the open ones oldest first, else newest
        first."""
        IndexJobs.reconcile(db_path)
        storage = open_storage(db_path or default_db_path())
        try:
            return [IndexJob.from_row(r) for r in storage.list_index_jobs(statuses, limit)]
        finally:
            storage.close()

    @staticmethod
    def pending(*, limit: int = 100, db_path: Path | None = None) -> builtins.list[IndexJob]:
        """Waiting and running jobs, oldest first."""
        jobs = IndexJobs.list(("queued", "running"), limit=limit, db_path=db_path)
        return sorted(jobs, key=lambda job: job.id)

    @staticmethod
    def queued(db_path: Path | None = None) -> builtins.list[IndexJob]:
        return IndexJobs.list(("queued",), limit=500, db_path=db_path)

    @staticmethod
    def claim_next(db_path: Path | None = None) -> IndexJob | None:
        storage = open_storage(db_path or default_db_path())
        try:
            row = storage.claim_next_index_job(IndexJobs._now())
            storage.commit()
            return IndexJob.from_row(row) if row is not None else None
        finally:
            storage.close()

    @staticmethod
    def mark_started(job_id: int, pid: int, db_path: Path | None = None) -> None:
        """A worker was launched for the job."""
        storage = open_storage(db_path or default_db_path())
        try:
            storage.mark_index_job_started(job_id, pid, IndexJobs._now())
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def attach_run(job_id: int, run_id: int, pid: int, db_path: Path | None = None) -> None:
        """The worker began run `run_id`."""
        storage = open_storage(db_path or default_db_path())
        try:
            storage.attach_index_job_run(job_id, run_id, pid)
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def finish(
        job_id: int, status: str, error: str | None = None, db_path: Path | None = None
    ) -> None:
        """Close a job that is still open (one that already ended is left as it is)."""
        storage = open_storage(db_path or default_db_path())
        try:
            storage.finish_index_job(job_id, status, IndexJobs._now(), error)
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def finish_for_run(
        run_id: int, run_status: str, error: str | None = None, db_path: Path | None = None
    ) -> None:
        """Close the job that was running as run `run_id`, to match how the run ended."""
        storage = open_storage(db_path or default_db_path())
        try:
            storage.finish_index_jobs_for_run(
                run_id, IndexJobs.job_status_for_run(run_status), IndexJobs._now(), error
            )
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def reconcile(db_path: Path | None = None) -> int:
        """Fail running jobs whose worker is gone (it was killed, or crashed before it could
        close the job). A running job with no pid yet belongs to a service that is about to
        start its worker, so it is left alone. Returns how many were failed."""
        from vethuq_core.index.runner import IndexRunner

        storage = open_storage(db_path or default_db_path())
        try:
            failed = 0
            for row in storage.list_index_jobs(("running",), 500):
                pid = row["pid"]
                if pid is None or IndexRunner._is_pid_running(pid):
                    continue
                storage.finish_index_job(
                    row["id"], "failed", IndexJobs._now(), IndexJobs.DIED_MESSAGE
                )
                failed += 1
            if failed:
                storage.commit()
            return failed
        finally:
            storage.close()

    @staticmethod
    def requeue(job_id: int, db_path: Path | None = None) -> None:
        storage = open_storage(db_path or default_db_path())
        try:
            storage.requeue_index_job(job_id)
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def requeue_running(db_path: Path | None = None) -> int:
        """Put jobs left 'running' by a service that died back in the queue."""
        storage = open_storage(db_path or default_db_path())
        try:
            count = storage.requeue_running_index_jobs()
            storage.commit()
            return count
        finally:
            storage.close()

    @staticmethod
    def prune(db_path: Path | None = None) -> None:
        """Forget all but the most recent finished jobs."""
        storage = open_storage(db_path or default_db_path())
        try:
            storage.prune_index_jobs(IndexJobs.KEEP_FINISHED)
            storage.commit()
        finally:
            storage.close()

    @staticmethod
    def cancel_queued(db_path: Path | None = None) -> int:
        storage = open_storage(db_path or default_db_path())
        try:
            count = storage.cancel_queued_index_jobs(IndexJobs._now())
            storage.commit()
            return count
        finally:
            storage.close()
