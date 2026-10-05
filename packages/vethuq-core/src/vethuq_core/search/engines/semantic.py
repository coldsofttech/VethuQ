"""The `semantic` search engine: pages whose passages mean what the query means.

The other engines match characters or words, so a query only finds text that contains it (or a
typo of it). This one matches *meaning*: the query and every chunk of every page are read into
vectors by a multilingual embedding model (see `vethuq_core.semantic`), and the chunks whose
vector points the same way as the query's are the hits. "Refund policy" finds "customers may
return goods for a full reimbursement", and a Telugu query finds the English page that says the
same thing.
"""

from __future__ import annotations

from collections import defaultdict

from vethuq_core.search.engines.base import SearchEngineUnavailable, SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.semantic import Embedders, SemanticIndex, SemanticModelError
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class SemanticSearchEngine:
    """`SearchEngine` that finds the passages closest in meaning to the query, best first.

    One `SearchMatch` per matching passage (`matched` is the whole passage), at most
    `MAX_HITS_PER_PAGE` a page, pages ordered by their best passage. `SearchMatch.score` is the
    cosine similarity of the passage and the query (1.0 is identical meaning). `threshold` is
    the least similarity a passage needs (default the user's setting; see
    `SearchSettings.SEMANTIC_PRESETS`) and the user's result limit caps the pages returned.

    It never matches case, or any other character-level option, so those raise `ValueError`.
    Pages that have no embedding yet are embedded first (`auto_index`), which on the first
    search of a collection takes a while, and downloads the model if needed. A model that
    can't be downloaded or loaded raises `SearchEngineUnavailable`.
    """

    name = "semantic"

    MAX_HITS_PER_PAGE = 3

    def __init__(self, storage: Storage, *, auto_index: bool = True) -> None:
        self._storage = storage
        self._auto_index = auto_index

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
        import numpy as np

        SearchEngineHelpers.require_no_level(self.name, level)
        SearchEngineHelpers.require_no_noise(self.name, noise)
        SearchEngineHelpers.require_no_unicode(self.name, unicode)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        if case_sensitive:
            raise ValueError("The semantic engine is always case-insensitive.")
        if not query.strip():
            return []
        minimum = (
            SearchSettings.get_semantic_threshold(self._storage)
            if threshold is None
            else SearchSettings.parse_semantic_threshold(threshold)
        )
        limit = SearchSettings.get_semantic_limit(self._storage)

        try:
            embedder = Embedders.get()
            if self._auto_index:
                SemanticIndex.sync(self._storage, embedder)
            query_vector = embedder.embed_query(query)
        except SemanticModelError as exc:
            raise SearchEngineUnavailable(str(exc)) from exc

        rows = self._storage.list_semantic_chunks(embedder.model, SemanticIndex.version())
        if not rows:
            return []
        matrix = np.frombuffer(b"".join(row["vector"] for row in rows), dtype=np.float32).reshape(
            len(rows), -1
        )
        scores = matrix @ query_vector

        # Cosine similarities are floats; accept the boundary the way `fuzzy` does.
        chosen = np.flatnonzero(scores >= minimum - 1e-6)
        by_page: dict[tuple[str, int], list[tuple[float, int, int]]] = defaultdict(list)
        for index in chosen:
            row = rows[int(index)]
            by_page[(row["kind"], row["page_id"])].append(
                (float(scores[index]), row["start_char"], row["end_char"])
            )
        if not by_page:
            return []

        ranked = sorted(by_page.items(), key=lambda item: (-max(h[0] for h in item[1]), item[0]))
        ranked = ranked[:limit]
        order = {page: position for position, (page, _) in enumerate(ranked)}

        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)
        found: list[tuple[int, str, int, list[SearchMatch]]] = []
        for kind in ("pdf", "image"):
            ids = [page_id for (page_kind, page_id) in order if page_kind == kind]
            for row in self._storage.list_semantic_page_rows(kind, ids):
                key = (kind, row["page_id"])
                text = row["ocr_text"].replace("\n", " ")
                page_number = row["page_number"]
                total_pages = (
                    page_counts.get(row["canonical_id"]) if page_number is not None else None
                )
                best = sorted(by_page[key], key=lambda hit: -hit[0])[
                    : SemanticSearchEngine.MAX_HITS_PER_PAGE
                ]
                hits = [
                    SearchEngineHelpers.build_match(
                        document_id=row["document_id"],
                        file_path=row["file_path"],
                        page_number=page_number,
                        total_pages=total_pages,
                        duplicate_of_path=row["duplicate_of_path"],
                        source=row["source"],
                        text=text,
                        start=min(start, len(text)),
                        end=min(end, len(text)),
                        chars=chars,
                        engine=self.name,
                        score=score,
                    )
                    for score, start, end in sorted(best, key=lambda hit: hit[1])
                ]
                found.append((order[key], row["file_path"], page_number or 0, hits))

        found.sort(key=lambda page: page[:3])
        return [hit for *_, hits in found for hit in hits]
