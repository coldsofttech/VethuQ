"""The background indexing service: install/control it, queue index runs for it, and run them."""

from __future__ import annotations

from vethuq_core.background.dispatch import Dispatch
from vethuq_core.background.service import (
    BackgroundService,
    BackgroundServiceError,
    ServiceState,
    ServiceStatus,
)
from vethuq_core.index.jobs import IndexJob, IndexJobs
from vethuq_core.index.submit import IndexSubmission

__all__ = [
    "BackgroundService",
    "BackgroundServiceError",
    "Dispatch",
    "IndexJob",
    "IndexJobs",
    "IndexSubmission",
    "ServiceState",
    "ServiceStatus",
]
