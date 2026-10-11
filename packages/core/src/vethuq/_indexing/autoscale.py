"""Lets a worker-scheduler add-on set how many files are read at once (`workers` = `auto`)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from vethuq._db import _Database, _FileFootprint
from vethuq_addon_api import Footprint, WorkerScheduler, WorkPlan


class _Governor:
    """A gate in front of the workers: a file starts only while fewer files are running than the
    scheduler allows. One file may always run, so a scheduler can slow a run but never stop it."""

    HISTORY = 20  # footprints handed to the scheduler
    KEPT = 500  # footprints kept in the database
    ASK_SECONDS = 1.0  # how often a waiting worker asks again

    _logger = logging.getLogger("vethuq.indexing")

    def __init__(
        self,
        database: _Database,
        scheduler: WorkerScheduler | None,
        ceiling: int,
        on_active: Callable[[int], None] | None = None,
    ) -> None:
        self._database = database
        self._scheduler = scheduler
        self.ceiling = max(1, ceiling)
        self._on_active = on_active
        self._active = 0
        self._queued = 0
        self._condition = threading.Condition()
        self._failed = False

    @property
    def active(self) -> int:
        return self._active

    def _limit(self) -> int:
        """What the scheduler allows now; its failure means the ceiling (the static estimate)."""
        if self._scheduler is None or self._failed:
            return self.ceiling
        try:
            plan = WorkPlan(self.ceiling, self._active, self._queued, self._history())
            return max(1, min(self.ceiling, int(self._scheduler.allowed(plan))))
        except Exception:  # noqa: BLE001 - a broken add-on must not stop the run
            self._logger.warning("The worker scheduler failed; using the static estimate.")
            self._failed = True
            return self.ceiling

    def _history(self) -> tuple[Footprint, ...]:
        with self._database.session() as session:
            rows = session.scalars(
                select(_FileFootprint).order_by(_FileFootprint.id.desc()).limit(self.HISTORY)
            ).all()
        return tuple(Footprint(r.size_bytes, r.pages, r.seconds, r.workers) for r in reversed(rows))

    def queue(self, count: int) -> None:
        with self._condition:
            self._queued += count

    @contextmanager
    def slot(self) -> Iterator[None]:
        """Wait for a turn, then hold it while a file is read."""
        with self._condition:
            while self._active > 0 and self._active >= self._limit():
                self._condition.wait(self.ASK_SECONDS)
            self._active += 1
            self._queued = max(0, self._queued - 1)
            active = self._active
        self._tell(active)
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                active = self._active
                self._condition.notify_all()
            self._tell(active)

    def _tell(self, active: int) -> None:
        if self._on_active is not None:
            self._on_active(active)

    def record(self, size_bytes: int, pages: int, seconds: float, workers: int) -> None:
        """Keep what reading a file took."""
        if pages <= 0 or seconds <= 0:
            return
        with self._database.session() as session:
            session.add(
                _FileFootprint(
                    recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    size_bytes=size_bytes,
                    pages=pages,
                    seconds=seconds,
                    workers=max(1, workers),
                )
            )
            session.flush()
            total = session.scalar(select(func.count()).select_from(_FileFootprint)) or 0
            if total > self.KEPT:
                oldest = session.scalars(
                    select(_FileFootprint.id).order_by(_FileFootprint.id).limit(total - self.KEPT)
                ).all()
                session.execute(delete(_FileFootprint).where(_FileFootprint.id.in_(oldest)))
