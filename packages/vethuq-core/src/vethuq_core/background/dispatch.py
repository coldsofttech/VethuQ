"""The background service's side of routing: whether indexing goes through it.

Requests themselves are submitted by `vethuq_core.index.Indexing.submit`, which asks this module
whether the service takes them.
"""

from __future__ import annotations

import time
from pathlib import Path

from vethuq_core.background.service import BackgroundService, ServiceState, ServiceStatus
from vethuq_core.index.jobs import IndexJobs
from vethuq_core.index.runner import IndexRunner, IndexState
from vethuq_core.paths import Paths
from vethuq_core.storage import default_db_path


class Dispatch:
    @staticmethod
    def service_status(db_path: Path | None = None) -> ServiceStatus | None:
        """The service's status when indexing goes through it, else None.

        That is when it is installed and works on the data folder `db_path` (default: this
        session's) belongs to. A service installed for another data folder - another user's, say
        - would run these jobs against the wrong database, so it is left out and indexing runs
        its own worker as before.
        """
        status = BackgroundService.status()
        if not status.installed:
            return None
        if status.home is not None and not BackgroundService.same_folder(
            status.home, Paths.data_root(db_path or default_db_path())
        ):
            return None
        return status

    @staticmethod
    def describe_state(service: ServiceStatus) -> str:
        """A phrase for the service's state, for messages."""
        if service.state == ServiceState.PAUSED:
            return "paused"
        if service.state == ServiceState.RUNNING:
            return "running"
        return service.state

    @staticmethod
    def wait_for_job(
        job_id: int, *, poll_seconds: float = 1.0, db_path: Path | None = None
    ) -> IndexState | None:
        """Block until the queued job has finished; returns the run's final state."""
        while True:
            job = IndexJobs.get(job_id, db_path)
            if job is None or job.status not in ("queued", "running"):
                return IndexRunner.read_state(db_path)
            time.sleep(poll_seconds)
