"""Search across previously OCR-indexed content.

`Search.indexed_content` is a thin facade over `vethuq_core.search.engines`: the matching
lives behind the `SearchEngine` interface so implementations can be swapped or chained.
"""

from __future__ import annotations

from dataclasses import dataclass

from vethuq_core.logs import Logs
from vethuq_core.search.engines import SearchEngines, SearchMatch
from vethuq_core.storage import Storage

# Searches always follow opening the database, which sets up this log.
_logger = Logs.get_logger("database")


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
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        engine: str | None = None,
    ) -> list[SearchMatch]:
        """Search indexed OCR text for `query` using the named (default: `like`) engine.

        Returns one `SearchMatch` per occurrence of `query`, ordered by file path
        (pages of the same PDF stay in page order, occurrences within a page in
        text order). Only successfully indexed documents are considered.
        """
        try:
            return SearchEngines.get(storage, engine).search(query, context_chars=context_chars)
        except Exception as exc:
            _logger.error(
                "Search failed: engine=%s query=%r error=%s: %s",
                engine or "default",
                query,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise

    @staticmethod
    def files(storage: Storage, query: str, *, context_chars: int | None = None) -> list[FileMatch]:
        """Search like `indexed_content`, but return one `FileMatch` per matching file.

        Files keep the order of their first matching page (so, by file path).
        """
        files: dict[int, FileMatch] = {}
        for match in Search.indexed_content(storage, query, context_chars=context_chars):
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
