"""Search across previously OCR-indexed content.

`Search.indexed_content` is a thin facade over `vethuq_core.search.engines`: the matching
lives behind the `SearchEngine` interface so implementations can be swapped or chained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from vethuq_core.logs import Logs
from vethuq_core.search.engines import SearchEngines, SearchMatch
from vethuq_core.settings import SearchSettings
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


class SearchOptionError(ValueError):
    """A search option combination that can't be honoured.

    `option` is which argument to blame: 'engine', 'case_sensitive' or 'threshold'.
    """

    def __init__(self, message: str, option: str) -> None:
        super().__init__(message)
        self.option = option


class SearchOptions(NamedTuple):
    """The resolved options a search runs with; `threshold` is set only for `fuzzy`."""

    engine: str
    case_sensitive: bool
    threshold: float | None = None


class Search:
    @staticmethod
    def resolve_options(
        storage: Storage,
        engine: str | None,
        case_sensitive: bool | None,
        threshold: float | str | None = None,
    ) -> SearchOptions:
        """Work out the engine, case sensitivity and fuzzy threshold to search with.

        Each falls back to its setting when None. The engines differ in what they
        can honour: `exact` is always case-sensitive and `full-text` never is, and
        only `fuzzy` has a similarity `threshold`. A preference that came from the
        *setting* is simply not applied where the engine can't use it, but one
        asked for explicitly that the engine can't honour raises
        `SearchOptionError` rather than being silently ignored - as does an
        unknown `engine` or a `threshold` that is neither a preset name nor a
        similarity in (0, 1].
        """
        if engine is not None and engine not in SearchSettings.ENGINES:
            raise SearchOptionError(
                f"{engine!r} is not one of {', '.join(SearchSettings.ENGINES)}.", "engine"
            )
        resolved_engine = engine if engine is not None else SearchSettings.get_engine(storage)
        if threshold is not None:
            try:
                threshold = SearchSettings.parse_fuzzy_threshold(threshold)
            except ValueError as exc:
                raise SearchOptionError(str(exc), "threshold") from exc
            if resolved_engine != "fuzzy":
                raise SearchOptionError(
                    "Only the fuzzy engine has a similarity threshold; "
                    "use --engine fuzzy (or the fuzzy engine) to set one.",
                    "threshold",
                )
        if resolved_engine == "full-text":
            if case_sensitive:
                raise SearchOptionError(
                    "The full-text engine is always case-insensitive; "
                    "use the like, exact or fuzzy engine for a case-sensitive search.",
                    "case_sensitive",
                )
            return SearchOptions(resolved_engine, False)
        if resolved_engine == "exact":
            if case_sensitive is False:
                raise SearchOptionError(
                    "The exact engine is always case-sensitive; "
                    "use the like, full-text or fuzzy engine for a case-insensitive search.",
                    "case_sensitive",
                )
            return SearchOptions(resolved_engine, True)
        if case_sensitive is None:
            case_sensitive = SearchSettings.is_case_sensitive(storage)
        if resolved_engine == "fuzzy":
            effective = (
                threshold if threshold is not None else SearchSettings.get_fuzzy_threshold(storage)
            )
            return SearchOptions(resolved_engine, case_sensitive, effective)
        return SearchOptions(resolved_engine, case_sensitive)

    @staticmethod
    def indexed_content(
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        engine: str | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
    ) -> list[SearchMatch]:
        """Search indexed OCR text for `query` using the named (default: `like`) engine.

        Returns one `SearchMatch` per occurrence of `query`, ordered by file path
        (pages of the same PDF stay in page order, occurrences within a page in
        text order) - or best match first for the ranked `full-text` and `fuzzy`
        engines. Only successfully indexed documents are considered. `like` is
        case-insensitive unless `case_sensitive`; `exact` is always case-sensitive;
        `full-text` can't be (asking for it raises `ValueError`). `fuzzy` finds words
        within `threshold` similarity (0-1, default the user's setting) of the
        query's; the other engines raise `ValueError` if given one.
        """
        try:
            return SearchEngines.get(storage, engine).search(
                query,
                context_chars=context_chars,
                case_sensitive=case_sensitive,
                threshold=threshold,
            )
        except Exception as exc:
            _logger.error(
                "Search failed: engine=%s case_sensitive=%s threshold=%s query_length=%d "
                "error=%s: %s",
                engine or "default",
                case_sensitive,
                threshold,
                len(query),
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise

    @staticmethod
    def files(
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        engine: str | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
    ) -> list[FileMatch]:
        """Search like `indexed_content`, but return one `FileMatch` per matching file.

        Files keep the order of their first matching page (so, by file path, or by
        relevance for the ranked `full-text` and `fuzzy` engines).
        """
        files: dict[int, FileMatch] = {}
        for match in Search.indexed_content(
            storage,
            query,
            context_chars=context_chars,
            engine=engine,
            case_sensitive=case_sensitive,
            threshold=threshold,
        ):
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
