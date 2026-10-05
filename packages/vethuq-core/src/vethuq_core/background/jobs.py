"""The queue of index runs waiting for the background service (the `index_jobs` table)."""

from __future__ import annotations

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
    requested_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def restart(self) -> bool:
        return self.mode == "restart"

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
            requested_at=row["requested_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


class IndexJobs:
    """Queue operations. Each call opens its own short-lived connection, so the CLI, the UI and
    the service can all use the queue at once without sharing a handle."""

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def enqueue(
        target: str | None,
        *,
        restart: bool = False,
        languages: str | None = None,
        db_path: Path | None = None,
    ) -> IndexJob:
        """Queue a run. An identical job already waiting is reused rather than added again, so
        something that asks repeatedly (the app's periodic rescan) can't pile jobs up."""
        storage = open_storage(db_path or default_db_path())
        try:
            mode = "restart" if restart else "run"
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
        for row in storage.list_index_jobs(None, 200):
            if row["id"] == job_id:
                return IndexJob.from_row(row)
        raise LookupError(f"index job {job_id} not found")

    @staticmethod
    def get(job_id: int, db_path: Path | None = None) -> IndexJob | None:
        storage = open_storage(db_path or default_db_path())
        try:
            for row in storage.list_index_jobs(None, 500):
                if row["id"] == job_id:
                    return IndexJob.from_row(row)
            return None
        finally:
            storage.close()

    @staticmethod
    def list(
        statuses: tuple[str, ...] | None = None,
        *,
        limit: int = 20,
        db_path: Path | None = None,
    ) -> list[IndexJob]:
        storage = open_storage(db_path or default_db_path())
        try:
            return [IndexJob.from_row(r) for r in storage.list_index_jobs(statuses, limit)]
        finally:
            storage.close()

    @staticmethod
    def queued(db_path: Path | None = None) -> list[IndexJob]:
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
    def finish(
        job_id: int, status: str, error: str | None = None, db_path: Path | None = None
    ) -> None:
        storage = open_storage(db_path or default_db_path())
        try:
            storage.finish_index_job(job_id, status, IndexJobs._now(), error)
            storage.commit()
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

    KEEP_FINISHED = 100

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
