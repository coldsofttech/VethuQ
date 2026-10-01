"""Deciding how many files to process at once, from the setting and machine headroom."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    pass

from vethuq_core.db.queries import Stats as StatsQuery
from vethuq_core.ocr.metrics import Metrics
from vethuq_core.ocr.pending import PendingFile
from vethuq_core.settings import IndexSettings

_logger = logging.getLogger(__name__)


class Scheduler:
    ENGINE_FOOTPRINT_MB = 700  # rough resident memory of one PaddleOCR CPU engine instance
    PDF_WEIGHT = 1.5  # a pending set that's mostly PDFs costs more per worker than mostly images
    CPU_BUSY_THRESHOLD = 70.0
    MEMORY_BUSY_THRESHOLD = 80.0

    @staticmethod
    def resolve_workers(conn: sqlite3.Connection, pending_type_counts: dict[str, int]) -> int:
        """Resolve the effective worker count for a run from the `thread_workers` setting.

        '0' disables concurrency entirely - the caller should process its file
        list sequentially, in its own thread, with no pool at all. '1'-'8' is
        used as given. 'auto' sizes workers dynamically from current CPU/memory
        headroom and the pending file mix - see `Scheduler.auto_worker_count`. Either
        way, the result never exceeds the number of pending files, since
        starting more workers than there is work to hand them doesn't help.
        """
        total_pending = sum(pending_type_counts.values())
        setting = IndexSettings.get_thread_workers(conn)
        workers = (
            Scheduler.auto_worker_count(pending_type_counts, total_pending)
            if setting == IndexSettings.THREAD_WORKERS_AUTO
            else int(setting)
        )
        return min(workers, total_pending) if total_pending and workers else workers

    @staticmethod
    def auto_worker_count(pending_type_counts: dict[str, int], total_pending: int) -> int:
        """Pick a worker count that uses headroom without pushing CPU/memory to their limit.

        Each worker loads its own OCR engine (see `Engine.get`), so the ceiling
        is set by whichever is scarcer: free CPU capacity, or free memory divided
        by one engine's rough footprint (`Scheduler.ENGINE_FOOTPRINT_MB`). A pending set
        that's mostly PDFs (multi-page, heavier to render/OCR than a single
        image) scales the result down further. Already-busy CPU or memory (past
        `Scheduler.CPU_BUSY_THRESHOLD`/`Scheduler.MEMORY_BUSY_THRESHOLD`) caps it at a single
        worker rather than trying to squeeze more out of an already-loaded
        machine.
        """
        if total_pending == 0:
            return 1

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        if (
            cpu_percent >= Scheduler.CPU_BUSY_THRESHOLD
            or memory.percent >= Scheduler.MEMORY_BUSY_THRESHOLD
        ):
            return 1

        cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 1
        cpu_headroom = max(1, round(cpu_count * (1 - cpu_percent / 100)))
        memory_headroom = max(
            1, int(memory.available / (1024 * 1024) / Scheduler.ENGINE_FOOTPRINT_MB)
        )

        pdf_share = pending_type_counts.get("pdf", 0) / total_pending
        weight = 1 + pdf_share * (Scheduler.PDF_WEIGHT - 1)
        workers = max(1, round(min(cpu_headroom, memory_headroom) / weight))

        return min(workers, IndexSettings.THREAD_WORKERS_MAX, total_pending)

    @staticmethod
    def would_exceed_budget(conn: sqlite3.Connection, item: PendingFile) -> bool:
        """Whether starting `item` right now would push CPU/memory past the busy thresholds.

        Projects live system usage (`psutil`, not just this run's own workers -
        other processes share the same headroom) forward by `item`'s historical
        footprint for its file_type + size bucket (`processing_metrics`). Missing
        file size or no history yet for that bucket both just skip the check -
        this only holds a file back when there's real evidence it would hurt,
        never on the strength of a guess. Caller already holds `db_lock`.
        """
        try:
            file_size_bytes = item.path.stat().st_size
        except OSError:
            return False

        row = StatsQuery.get_processing_metrics_budget_row(
            conn, 1, item.file_type, Metrics.size_bucket(file_size_bytes)
        )
        if row is None:
            return False

        memory = psutil.virtual_memory()
        projected_memory_percent = memory.percent + (
            row["avg_peak_memory_mb"] / (memory.total / (1024 * 1024)) * 100
        )
        # interval=None (non-blocking, delta since the last call) rather than the
        # brief blocking sample `Scheduler.auto_worker_count` takes once per run - this is
        # checked on every dequeue attempt, far too often to afford a sleep each time.
        projected_cpu_percent = psutil.cpu_percent(interval=None) + row["avg_cpu_percent"]
        return (
            projected_memory_percent >= Scheduler.MEMORY_BUSY_THRESHOLD
            or projected_cpu_percent >= Scheduler.CPU_BUSY_THRESHOLD
        )

    @staticmethod
    def batch_workers(conn: sqlite3.Connection, initial: int, *, first: bool) -> int:
        """Worker count for a quick-pass batch: `initial` for the run's first, then the setting."""
        if first:
            return initial
        setting = IndexSettings.get_thread_workers(conn)
        return 1 if setting == IndexSettings.THREAD_WORKERS_AUTO else int(setting)
