"""Background OCR indexing runs."""

from __future__ import annotations

from vethuq_core.index.eta import Eta
from vethuq_core.index.rebuild import SearchIndexRebuild, SearchIndexRebuildResult
from vethuq_core.index.reindex import AmbiguousFileError, FileNotTrackedError, Reindex
from vethuq_core.index.runner import (
    AlreadyRunningError,
    DatabaseIntegrityError,
    IndexRun,
    IndexRunner,
    IndexRunnerError,
    IndexState,
    StaleLockError,
)

__all__ = [
    "AlreadyRunningError",
    "AmbiguousFileError",
    "DatabaseIntegrityError",
    "Eta",
    "FileNotTrackedError",
    "IndexRun",
    "IndexRunner",
    "IndexRunnerError",
    "IndexState",
    "Reindex",
    "SearchIndexRebuild",
    "SearchIndexRebuildResult",
    "StaleLockError",
]
