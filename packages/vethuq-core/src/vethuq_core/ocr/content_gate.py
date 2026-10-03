"""Ordering for files with identical content when several are processed at once."""

from __future__ import annotations

import threading
from pathlib import Path

from vethuq_core.ocr.document import Document


class ContentGate:
    """Makes the first file (in run order) of each identical-content group the original.

    Files are checksummed before being claimed; one whose content matches an
    earlier file in the run waits for that file to finish, so it is recorded as
    its duplicate rather than racing it into a second OCR pass. Without this,
    which copy ends up as the original depended on thread timing. Files with
    distinct content never wait on each other. A caller must start items in
    index order (as a pool fed from the sorted list does) so earlier items are
    always running, never queued behind a waiter.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._registered: set[int] = set()
        self._prefix = 0  # every index below this has registered its checksum
        self._open: dict[str, list[int]] = {}  # checksum -> unfinished indices
        self._sha_by_index: dict[int, str | None] = {}

    def enter(self, index: int, path: Path) -> None:
        try:
            sha: str | None = Document.compute_sha256(path)
        except OSError:
            sha = None  # vanished or unreadable: processing records that itself
        with self._cond:
            self._sha_by_index[index] = sha
            self._registered.add(index)
            if sha is not None:
                self._open.setdefault(sha, []).append(index)
            while self._prefix in self._registered:
                self._prefix += 1
            self._cond.notify_all()
            if sha is not None:
                self._cond.wait_for(lambda: self._prefix >= index and min(self._open[sha]) == index)

    def leave(self, index: int) -> None:
        with self._cond:
            sha = self._sha_by_index.get(index)
            if sha is not None:
                self._open[sha].remove(index)
            self._cond.notify_all()
