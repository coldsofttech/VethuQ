"""The one path every index request takes: a row in `index_jobs`, then a worker to run it.

Every entry point (the CLI, the desktop app, the `vethuq` Python functions, reindex) calls
`Indexing.submit`. It validates the request, records it as an `index_jobs` row, and then either

- leaves the row queued for the background service, when this build has the service and it is
  installed (for this data folder); the service claims and runs it; or
- starts a worker of its own for the row (a one-off), straight away - always, in the `vethuq`
  pip package, which ships without the service (`packages/vethuq/scripts/merge_sources.py`).

Either way the worker that runs the job records its run on the row and closes it, so
`vethuq index queue list` shows every request however it was run. A one-off request while a run
is already active is refused, as before, and its row is recorded as failed.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vethuq_core.hints import Hints
from vethuq_core.index.jobs import IndexJobs
from vethuq_core.index.runner import IndexRunner, IndexRunnerError
from vethuq_core.storage import default_db_path, open_storage


@dataclass
class IndexSubmission:
    """What became of an index request."""

    pid: int | None  # the worker's pid when it was started directly (one-off)
    job_id: int | None  # the request's `index_jobs` id
    service: Any | None  # the service's `ServiceStatus` when the request was queued for it

    @property
    def queued(self) -> bool:
        """Left for the background service rather than started in a worker of its own."""
        return self.pid is None and self.job_id is not None

    @property
    def service_idle(self) -> bool:
        """Queued, but the service isn't taking jobs right now (stopped or paused)."""
        return self.queued and self.service is not None and not self.service.running


class Indexing:
    VIA_AUTO = "auto"  # the service if it is installed, else a one-off
    VIA_SERVICE = "service"
    VIA_ONE_OFF = "one-off"

    @staticmethod
    def has_service() -> bool:
        """Whether this build includes the background service (the pip package does not)."""
        return importlib.util.find_spec(f"{__package__.rsplit('.', 1)[0]}.background") is not None

    @staticmethod
    def service_status(db_path: Path | None = None) -> Any | None:
        """The service's status when indexing goes through it, else None (always None without
        the service)."""
        if not Indexing.has_service():
            return None
        from vethuq_core.background.dispatch import Dispatch

        return Dispatch.service_status(db_path)

    @staticmethod
    def describe_state(service: Any) -> str:
        from vethuq_core.background.dispatch import Dispatch

        return Dispatch.describe_state(service)

    @staticmethod
    def submit(
        target: str | None = None,
        *,
        restart: bool = False,
        languages: str | None = None,
        force: bool = False,
        via: str = VIA_AUTO,
        db_path: Path | None = None,
        on_recovery: Callable[[list[str]], None] | None = None,
    ) -> IndexSubmission:
        service = Indexing.service_status(db_path) if via != Indexing.VIA_ONE_OFF else None
        if via == Indexing.VIA_SERVICE and service is None:
            raise IndexRunnerError(
                "The background service isn't installed. "
                f"Install it with '{Hints.command('background-service install')}'."
            )
        db = db_path or default_db_path()
        IndexJobs.prune(db)  # a periodic caller (the app's rescan) would otherwise grow the table
        # The same checks a direct start makes, so a bad source or language is reported now,
        # and never recorded as a job.
        storage = open_storage(db)
        try:
            IndexRunner.validate_request(storage, target, languages)
        finally:
            storage.close()

        if service is not None:
            job = IndexJobs.enqueue(target, restart=restart, languages=languages, db_path=db)
            return IndexSubmission(pid=None, job_id=job.id, service=service)

        job = IndexJobs.enqueue(
            target, restart=restart, languages=languages, coalesce=False, db_path=db
        )
        try:
            pid = IndexRunner.start_run(
                target,
                force=force,
                restart=restart,
                db_path=db_path,
                on_recovery=on_recovery,
                languages=languages,
                job_id=job.id,
            )
        except Exception as exc:
            # e.g. a run is already in progress: kept as a failed job, with the reason
            IndexJobs.finish(job.id, "failed", str(exc), db)
            raise
        return IndexSubmission(pid=pid, job_id=job.id, service=None)
