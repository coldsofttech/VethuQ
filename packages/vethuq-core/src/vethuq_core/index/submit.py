"""Where an index request goes: the background service's queue, or a worker of its own.

The background service (`vethuq_core.background`) ships with the desktop build only; the `vethuq`
pip package leaves it out (see `packages/vethuq/scripts/merge_sources.py`). Everything that
starts indexing goes through `Indexing.submit`, which routes to the service when it is there and
installed, and otherwise - always, in the pip package - starts a one-off worker with
`IndexRunner.start_run`.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vethuq_core.index.runner import IndexRunner


@dataclass
class IndexSubmission:
    """What became of an index request."""

    pid: int | None  # the worker's pid when it was started directly (one-off)
    job_id: int | None  # the queued job's id when it went to the service
    service: Any | None  # the service's `ServiceStatus` when the request was queued

    @property
    def queued(self) -> bool:
        return self.job_id is not None

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
        if Indexing.has_service():
            from vethuq_core.background.dispatch import Dispatch

            return Dispatch.submit(
                target,
                restart=restart,
                languages=languages,
                force=force,
                via=via,
                db_path=db_path,
                on_recovery=on_recovery,
            )
        pid = IndexRunner.start_run(
            target,
            force=force,
            restart=restart,
            db_path=db_path,
            on_recovery=on_recovery,
            languages=languages,
        )
        return IndexSubmission(pid=pid, job_id=None, service=None)
