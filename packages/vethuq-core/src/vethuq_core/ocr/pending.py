"""Finding the files a run would actually (re)process."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from vethuq_core.db.queries import Document as DocumentQuery
from vethuq_core.logs import Logs
from vethuq_core.ocr.document import Document
from vethuq_core.ocr.reader import Readers
from vethuq_core.source import Source

_logger = Logs.get_logger("index")


@dataclass(frozen=True)
class PendingFile:
    source: Source
    path: Path
    file_type: str


class Pending:
    @staticmethod
    def iter_files(
        conn: sqlite3.Connection,
        source: Source,
        *,
        only_new_files: bool = False,
        only_failed: bool = False,
        exclude_paths: Collection[str] = (),
    ) -> Iterator[tuple[Path, str]]:
        """Yield `(file_path, file_type)` for files `Quick.run` would actually (re)process.

        Mirrors the skip logic in `Quick.run` so callers (e.g. progress/ETA
        reporting) can size a run before starting it. `exclude_paths` are files
        to leave out regardless - e.g. ones this run already attempted, so a file
        that failed isn't picked up again as "still pending".
        """
        root = Path(source.path)
        for file_path in Readers.iter_files(root):
            if str(file_path) in exclude_paths:
                continue
            existing = None
            if only_new_files or only_failed:
                existing = DocumentQuery.get_index_pending_check(conn, str(file_path))
            if only_failed:
                if existing is None or existing["status"] != "error":
                    continue
            elif (
                only_new_files
                and existing is not None
                and existing["status"] == "indexed"
                and not Document.has_content_changed(file_path, existing)
            ):
                continue
            file_type = Readers.for_path(file_path).file_type
            yield file_path, file_type

    @staticmethod
    def file_count(
        conn: sqlite3.Connection,
        source: Source,
        *,
        only_new_files: bool = False,
        only_failed: bool = False,
    ) -> int:
        """Count the files `Quick.run` would actually (re)process for `source`."""
        return sum(
            1
            for _ in Pending.iter_files(
                conn, source, only_new_files=only_new_files, only_failed=only_failed
            )
        )

    @staticmethod
    def file_type_counts(
        conn: sqlite3.Connection,
        source: Source,
        *,
        only_new_files: bool = False,
        only_failed: bool = False,
    ) -> dict[str, int]:
        """Like `Pending.file_count`, but broken down by file_type ('pdf'/'image').

        Used to weight ETA estimates by each file type's own average OCR
        duration (`processing_metrics`), since a source's remaining files may be
        a mix of pdfs and images that OCR at very different speeds.
        """
        counts = Readers.new_file_type_counts()
        for _, file_type in Pending.iter_files(
            conn, source, only_new_files=only_new_files, only_failed=only_failed
        ):
            counts[file_type] += 1
        return counts
