"""Route an index request to the background service's queue, or run it on the spot.

Every `index *` entry point (the CLI, the desktop app, the `vethuq` Python API) goes through
`Dispatch.submit`. When the service is installed the request is queued for it; otherwise - or
when the caller asks for a one-off - it is started directly as before.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from vethuq_core.background.jobs import IndexJobs
from vethuq_core.background.service import BackgroundService, ServiceState, ServiceStatus
from vethuq_core.index.runner import IndexRunner, IndexState
from vethuq_core.index.submit import IndexSubmission
from vethuq_core.paths import Paths
from vethuq_core.storage import default_db_path, open_storage


class Dispatch:
    VIA_AUTO = "auto"  # the service if it is installed, else a one-off
    VIA_SERVICE = "service"
    VIA_ONE_OFF = "one-off"

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
        service = Dispatch.service_status(db_path) if via != Dispatch.VIA_ONE_OFF else None
        if via == Dispatch.VIA_SERVICE and service is None:
            from vethuq_core.index.runner import IndexRunnerError

            raise IndexRunnerError(
                "The background service isn't installed. "
                "Install it with 'vethuq background-service install'."
            )
        if service is None:
            pid = IndexRunner.start_run(
                target,
                force=force,
                restart=restart,
                db_path=db_path,
                on_recovery=on_recovery,
                languages=languages,
            )
            return IndexSubmission(pid=pid, job_id=None, service=None)

        # The same checks a direct start makes, so a bad source or language is reported now
        # rather than only in the service's log.
        db_path = db_path or default_db_path()
        storage = open_storage(db_path)
        try:
            IndexRunner.validate_request(storage, target, languages)
        finally:
            storage.close()
        job = IndexJobs.enqueue(target, restart=restart, languages=languages, db_path=db_path)
        return IndexSubmission(pid=None, job_id=job.id, service=service)

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
