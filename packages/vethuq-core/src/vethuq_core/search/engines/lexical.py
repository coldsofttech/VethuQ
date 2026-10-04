"""The `lexical` search engine: FTS5 trigram retrieval, ranked by relevance (BM25)."""

from __future__ import annotations

from vethuq_core.search.engines.base import SearchMatch, SearchQueryError
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.engines.like import LikeSearchEngine
from vethuq_core.storage import Storage


class LexicalSearchEngine:
    """`SearchEngine` that retrieves pages through the FTS5 trigram index, best match first.

    Finds `query` as a substring anywhere in a page's text, mid-word included
    (`mus` finds "Museum"), like `like` - but the pages come straight from an FTS5
    `MATCH` and are ordered by BM25 relevance (`SearchMatch.score`) rather than by
    file path. Case-insensitive unless `case_sensitive` is set. The trigram index
    needs at least three characters, so a shorter query is rejected.
    """

    name = "lexical"

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def search(
        self,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
    ) -> list[SearchMatch]:
        SearchEngineHelpers.require_no_level(self.name, level)
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        if not query:
            return []
        expression = SearchEngineHelpers.trigram_match(query)
        if expression is None:
            raise SearchQueryError(
                f"The lexical engine needs at least {SearchEngineHelpers.TRIGRAM_MIN_CHARS} "
                "characters; use the like engine for shorter queries."
            )

        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        matches: list[SearchMatch] = []
        for row in (
            *self._storage.search_lexical_pdf_pages(expression),
            *self._storage.search_lexical_image_pages(expression),
        ):
            page_number = row["page_number"]
            text = row["ocr_text"].replace("\n", " ")
            total_pages = page_counts.get(row["canonical_id"]) if page_number is not None else None
            for start, end in LikeSearchEngine._occurrences(
                text, query, case_sensitive=case_sensitive
            ):
                matches.append(
                    SearchEngineHelpers.build_match(
                        document_id=row["document_id"],
                        file_path=row["file_path"],
                        page_number=page_number,
                        total_pages=total_pages,
                        duplicate_of_path=row["duplicate_of_path"],
                        source=row["source"],
                        text=text,
                        start=start,
                        end=end,
                        chars=chars,
                        engine=self.name,
                        score=row["score"],
                    )
                )

        # Best page first; ties (and the PDF/image split above) fall back to
        # file path then page. Stable, so occurrences keep their text order.
        matches.sort(key=lambda m: (-(m.score or 0.0), m.file_path, m.page_number or 0))
        return matches
