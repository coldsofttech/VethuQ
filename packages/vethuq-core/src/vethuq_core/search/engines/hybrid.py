"""`semantic` combined with a keyword engine: one ranking from meaning and from words.

Semantic search is weak where keyword search is strong - an invoice number, a name, an exact
phrase - and the other way round. Combining them (the `search semantic combine` setting) runs
both and ranks the pages by *reciprocal rank fusion*: a page scores the sum, over the engines
that found it, of `1 / (K + its position in that engine's ranking)`. Only the positions count,
because the engines' scores (a cosine, BM25) can't be compared, and a page both engines like
rises above a page only one of them found.
"""

from __future__ import annotations

from dataclasses import replace

from vethuq_core.search.engines.base import (
    SearchEngine,
    SearchEngineUnavailable,
    SearchMatch,
    SearchQueryError,
)


class HybridSearchEngine:
    """`SearchEngine` over a semantic engine and a keyword engine, ranked together.

    Its hits are those of both engines, each labelled with the engine that found it
    (`SearchMatch.engine`, so a passage is `semantic` and a keyword hit `full-text`), pages in
    fused order and, within a page, in text order. `matched_by` lists the engines that found the
    hit's *page*, and `score` stays the engine's own. A keyword engine that can't search the
    query (`lexical` needs three characters) just contributes nothing; the semantic engine
    failing fails the search.
    """

    name = "semantic"

    # The usual constant of reciprocal rank fusion: how quickly a lower position stops counting.
    RANK_CONSTANT = 60

    def __init__(self, semantic: SearchEngine, keyword: SearchEngine) -> None:
        self._semantic = semantic
        self._keyword = keyword

    @staticmethod
    def _page_order(matches: list[SearchMatch]) -> list[tuple[int, int | None]]:
        """The pages of `matches` in order of first appearance (the engines return best first)."""
        order: dict[tuple[int, int | None], None] = {}
        for match in matches:
            order.setdefault((match.file_id, match.page_number), None)
        return list(order)

    def search(
        self,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> list[SearchMatch]:
        semantic = self._semantic.search(
            query,
            context_chars=context_chars,
            case_sensitive=case_sensitive,
            threshold=threshold,
            distance=distance,
            level=level,
            noise=noise,
            unicode=unicode,
        )
        try:
            keyword = self._keyword.search(query, context_chars=context_chars)
        except (SearchQueryError, SearchEngineUnavailable):
            keyword = []

        fused: dict[tuple[int, int | None], float] = {}
        found_by: dict[tuple[int, int | None], list[str]] = {}
        for engine, matches in ((self._semantic.name, semantic), (self._keyword.name, keyword)):
            for position, page in enumerate(HybridSearchEngine._page_order(matches), start=1):
                fused[page] = fused.get(page, 0.0) + 1 / (
                    HybridSearchEngine.RANK_CONSTANT + position
                )
                found_by.setdefault(page, []).append(engine)

        pages: dict[tuple[int, int | None], list[SearchMatch]] = {}
        for match in (*semantic, *keyword):
            pages.setdefault((match.file_id, match.page_number), []).append(match)

        ordered = sorted(
            fused, key=lambda page: (-fused[page], pages[page][0].file_path, page[1] or 0)
        )
        results: list[SearchMatch] = []
        for page in ordered:
            engines = tuple(found_by[page])
            hits = sorted(pages[page], key=lambda hit: (hit.start or 0, hit.engine or ""))
            results.extend(replace(hit, matched_by=engines) for hit in hits)
        return results
