"""Helpers for running files side by side: one at a time per content, and how many at once."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psutil


class _ContentGate:
    """Lets only one worker handle a given content (SHA-256) at a time, so files with the same
    content are read once: the others then find the document ready and share it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def hold(self, sha256: str) -> Iterator[None]:
        with self._lock:
            lock, users = self._held.get(sha256, (threading.Lock(), 0))
            self._held[sha256] = (lock, users + 1)
        with lock:
            try:
                yield
            finally:
                with self._lock:
                    lock, users = self._held[sha256]
                    if users <= 1:
                        del self._held[sha256]
                    else:
                        self._held[sha256] = (lock, users - 1)


class _Scheduler:
    MAX_WORKERS = 8
    MEMORY_PER_WORKER = 1.5 * 1024**3  # OCR models and page images

    @staticmethod
    def auto() -> int:
        """Workers the machine can carry: about one per two cores, limited by free memory."""
        cores = psutil.cpu_count(logical=False) or os.cpu_count() or 2
        by_memory = int(psutil.virtual_memory().available // _Scheduler.MEMORY_PER_WORKER)
        return max(1, min(_Scheduler.MAX_WORKERS, max(1, cores // 2), max(1, by_memory)))

    @staticmethod
    def resolve(requested: int | str | None, configured: int | str) -> int:
        value = requested if requested is not None else configured
        return _Scheduler.auto() if value == "auto" else int(value)
