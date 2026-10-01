"""The public entry point: quick pass first, then the deeper phases, round by round."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from vethuq_core.ocr.deepening import Deepening
from vethuq_core.ocr.pending import Pending
from vethuq_core.ocr.quick import Quick
from vethuq_core.ocr.scheduler import Scheduler
from vethuq_core.source import Source

_logger = logging.getLogger(__name__)


class Ocr:
    @staticmethod
    def has_pending_quick_work(
        conn: sqlite3.Connection, sources: list[Source], attempted: Collection[str]
    ) -> bool:
        """Whether any file under `sources` still needs its first (quick) pass."""
        return any(
            True
            for source in sources
            for _ in Pending.iter_files(
                conn, source, only_new_files=source.status != "pending", exclude_paths=attempted
            )
        )

    @staticmethod
    def run_phased(
        conn: sqlite3.Connection,
        resolve_sources: Callable[[], list[Source]],
        *,
        only_failed: bool = False,
        workers: int = 1,
        on_file_start: Callable[[str], None] | None = None,
        on_file_done: Callable[[str, bool], None] | None = None,
        on_workers_changed: Callable[[int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        on_files_queued: Callable[[int], None] | None = None,
        on_unit_start: Callable[[str, int], None] | None = None,
        on_unit_done: Callable[[str], None] | None = None,
    ) -> list[str]:
        """Index everything under the sources `resolve_sources()` returns, phase by phase.

        Quick first, always: every file gets its phase-1 pass (`Quick.run_batch`)
        before any deeper work starts, so it's searchable right away. Only once
        nothing is waiting do the `index_engine` setting's deeper phases run -
        moderate pages before deep ones - and the moment a new or changed file
        appears (checked between angle passes) that work gives way: the file gets
        its quick pass, then the deeper work resumes. `resolve_sources` is
        called afresh each round so sources added mid-run are picked up too.

        `only_failed` applies to the first round only (a "restart" retries
        failures, then carries on as normal). Files attempted once this run are
        never retried by a later round, so a failing file can't keep the run
        alive. `on_files_queued(n)` reports `n` more files found in a later
        round (the first round's count is the caller's to know). The other
        callbacks are `Quick.run_batch`'s and `Deepening.run_batch`'s.

        Returns the paths of the files that got their quick pass this run.
        """
        attempted: set[str] = set()
        skip_units: set[tuple[str, int]] = set()
        processed: list[str] = []
        first = True

        def quick_work_waiting() -> bool:
            return Ocr.has_pending_quick_work(conn, resolve_sources(), attempted)

        while True:
            if should_stop is not None and should_stop():
                break
            sources = resolve_sources()
            done = Quick.run_batch(
                conn,
                sources,
                only_failed=only_failed and first,
                workers=Scheduler.batch_workers(conn, workers, first=first),
                on_file_start=on_file_start,
                on_file_done=on_file_done,
                on_workers_changed=on_workers_changed,
                should_stop=should_stop,
                exclude_paths=attempted,
                on_pending=None if first else on_files_queued,
            )
            first = False
            attempted.update(done)
            processed.extend(done)
            if done:
                continue  # more quick work may have arrived while that batch ran

            if should_stop is not None and should_stop():
                break
            passes = Deepening.run_batch(
                conn,
                sources,
                max_phase=Deepening.max_phase(conn),
                should_stop=should_stop,
                has_quick_work=quick_work_waiting,
                skip_units=skip_units,
                on_unit_start=on_unit_start,
                on_unit_done=on_unit_done,
            )
            if passes == 0:
                break
        return processed
