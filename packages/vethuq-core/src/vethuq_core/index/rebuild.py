"""Manual rebuild of the full-text search tables from stored page text."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vethuq_core.index.runner import AlreadyRunningError, IndexRunner
from vethuq_core.logs import Logs
from vethuq_core.storage import default_db_path, open_storage


@dataclass
class SearchIndexRebuildResult:
    """Outcome of a rebuild: pages per rebuilt index, failures by index, elapsed seconds."""

    rebuilt: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed


class SearchIndexRebuild:
    """Rebuild every FTS5 search table from the page text already stored in the database.

    No file is re-read or re-OCR'd. A failing index is reported and skipped so the
    others still get rebuilt.
    """

    @staticmethod
    def run(
        *,
        db_path: Path | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> SearchIndexRebuildResult:
        """Rebuild all search tables. `on_progress(index, position, total)` fires before each."""
        db_path = db_path or default_db_path()
        log = Logs.setup("index", db_path)
        running, pid = IndexRunner.is_running(db_path)
        if running:
            raise AlreadyRunningError(f"An index run is already in progress (pid {pid}).")

        result = SearchIndexRebuildResult()
        start = time.monotonic()
        storage = open_storage(db_path)
        try:
            indexes = storage.search_index_names()
            for position, index in enumerate(indexes, start=1):
                if on_progress is not None:
                    on_progress(index, position, len(indexes))
                try:
                    with storage.transaction():
                        result.rebuilt[index] = storage.rebuild_search_index(index)
                except sqlite3.Error as exc:
                    result.failed[index] = str(exc)
                    log.error("Search index rebuild failed for %s: %s", index, exc)
                else:
                    log.info("Rebuilt search index %s (%d pages)", index, result.rebuilt[index])
        finally:
            storage.close()
        result.seconds = time.monotonic() - start
        log.info(
            "Search index rebuild finished: %d rebuilt, %d failed in %.1fs",
            len(result.rebuilt),
            len(result.failed),
            result.seconds,
        )
        return result
