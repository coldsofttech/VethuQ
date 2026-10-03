"""Search across previously OCR-indexed content.

`Search.indexed_content` is a thin facade over `vethuq_core.search.engines`: the matching
lives behind the `SearchEngine` interface so implementations can be swapped or chained.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from vethuq_core.search.engines import SearchEngines, SearchMatch


@dataclass(frozen=True)
class FileMatch:
    """One file with at least one matching page - `SearchMatch`es collapsed per file."""

    file_id: int
    file_name: str
    file_path: str
    is_duplicate: bool


class Search:
    @staticmethod
    def indexed_content(
        conn: sqlite3.Connection,
        query: str,
        *,
        context_chars: int | None = None,
        engine: str | None = None,
    ) -> list[SearchMatch]:
        """Search indexed OCR text for `query` using the named (default: `like`) engine.

        Returns one `SearchMatch` per matching page, ordered by file path (pages of
        the same PDF stay in page order). Only successfully indexed documents are
        considered. When a page contains `query` more than once, only its first
        occurrence is used.
        """
        return SearchEngines.get(conn, engine).search(query, context_chars=context_chars)

    @staticmethod
    def files(
        conn: sqlite3.Connection, query: str, *, context_chars: int | None = None
    ) -> list[FileMatch]:
        """Search like `indexed_content`, but return one `FileMatch` per matching file.

        Files keep the order of their first matching page (so, by file path).
        """
        files: dict[int, FileMatch] = {}
        for match in Search.indexed_content(conn, query, context_chars=context_chars):
            files.setdefault(
                match.file_id,
                FileMatch(
                    file_id=match.file_id,
                    file_name=match.file_name,
                    file_path=match.file_path,
                    is_duplicate=match.duplicate_of_path is not None,
                ),
            )
        return list(files.values())
