"""The `proximity` search engine: pages where all the query's terms occur close together."""

from __future__ import annotations

import re
from bisect import bisect_left

from vethuq_core.search.engines.base import SearchMatch, SearchQueryError
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.engines.fulltext import FullTextSearchEngine
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class ProximitySearchEngine:
    """`SearchEngine` that finds passages where all the query's terms sit within N words.

    Each word or `"quoted phrase"` of the query is a term (`mus*` is a prefix);
    at least two are needed. They may appear in any order, and every term
    matches like `full-text` does (any case, English word forms). N - `distance`,
    10 words by default - is the most words that may lie between the first and the
    last term of a passage; 0 would be a phrase, which `full-text` already
    supports. One `SearchMatch` per passage, spanning first term to last, on pages
    ranked by relevance (`SearchMatch.score`). Always case-insensitive.
    """

    name = "proximity"

    # The word boundaries FTS5's `unicode61` tokenizer uses: runs of letters and digits.
    _TOKEN = re.compile(r"[^\W_]+")

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
        noise: str | None = None,
    ) -> list[SearchMatch]:
        if case_sensitive:
            raise ValueError("The proximity engine is always case-insensitive.")
        SearchEngineHelpers.require_no_level(self.name, level)
        SearchEngineHelpers.require_no_noise(self.name, noise)
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        limit = (
            SearchSettings.get_proximity_distance(self._storage)
            if distance is None
            else SearchSettings.parse_proximity_distance(distance)
        )
        # The same term twice (in any case) is still one term to find near the others.
        terms = list(
            {term.casefold(): term for term in FullTextSearchEngine.parse_terms(query)}.values()
        )
        if not terms:
            return []
        if len(terms) < 2:
            raise SearchQueryError(
                "Proximity search needs at least two words or phrases; "
                "use the full-text engine to search for one."
            )

        expression = f"NEAR({' '.join(terms)}, {limit})"
        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        pdf_rows = list(self._storage.search_proximity_pdf_pages(expression))
        image_rows = list(self._storage.search_proximity_image_pages(expression))
        pdf_highlights = ProximitySearchEngine._term_highlights(
            terms, pdf_rows, self._storage.get_pdf_term_highlights
        )
        image_highlights = ProximitySearchEngine._term_highlights(
            terms, image_rows, self._storage.get_image_term_highlights
        )

        matches: list[SearchMatch] = []
        for rows, highlights in ((pdf_rows, pdf_highlights), (image_rows, image_highlights)):
            for row in rows:
                texts_and_spans = [
                    FullTextSearchEngine._highlighted_spans(
                        per_term[row["page_id"]].replace("\n", " ")
                    )
                    for per_term in highlights
                    if row["page_id"] in per_term
                ]
                if len(texts_and_spans) != len(terms):
                    continue  # a term couldn't be located again, so no passage can be shown
                text = texts_and_spans[0][0]
                passages = ProximitySearchEngine.find_clusters(
                    text, [spans for _, spans in texts_and_spans], limit
                )
                page_number = row["page_number"]
                total_pages = (
                    page_counts.get(row["canonical_id"]) if page_number is not None else None
                )
                for start, end in passages:
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

        # Best page first; ties (and the PDF/image split above) fall back to file
        # path then page. Stable, so a page's passages keep their text order.
        matches.sort(key=lambda m: (-(m.score or 0.0), m.file_path, m.page_number or 0))
        return matches

    @staticmethod
    def find_clusters(
        text: str, term_spans: list[list[tuple[int, int]]], distance: int
    ) -> list[tuple[int, int]]:
        """The `(start, end)` of each passage of `text` holding every term within `distance` words.

        `term_spans[i]` are the spans of term `i` in `text`. A passage qualifies when,
        from the end of its first term to the start of its last, no more than
        `distance` words lie between (other terms in between count as words) -
        exactly how FTS5's `NEAR(a b c, distance)` decides, in either order.
        Overlapping passages are merged into one.
        """
        if not term_spans or not all(term_spans):
            return []
        starts = [m.start() for m in ProximitySearchEngine._TOKEN.finditer(text)]

        def words_between(first_end: int, last_start: int) -> int:
            return max(0, bisect_left(starts, last_start) - bisect_left(starts, first_end))

        events = sorted(
            (start, end, term) for term, spans in enumerate(term_spans) for start, end in spans
        )
        needed = len(term_spans)
        in_window = [0] * needed
        covered = 0
        left = 0
        passages: list[tuple[int, int]] = []
        for right, (last_start, last_end, term) in enumerate(events):
            in_window[term] += 1
            if in_window[term] == 1:
                covered += 1
            # Shrink from the left while every term is still present: the smallest
            # window ending here is the one most likely to be close enough.
            while covered == needed:
                first_start, first_end, first_term = events[left]
                if in_window[first_term] > 1:
                    in_window[first_term] -= 1
                    left += 1
                    continue
                if words_between(first_end, last_start) <= distance:
                    end = max(e for _, e, _ in events[left : right + 1])
                    passages.append((first_start, max(end, last_end)))
                in_window[first_term] -= 1
                covered -= 1
                left += 1

        merged: list[tuple[int, int]] = []
        for start, end in sorted(passages):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def _term_highlights(terms, rows, fetch) -> list[dict[int, str]]:
        """For each term, the highlighted text of the rows' pages it occurs on, by page id."""
        page_ids = [row["page_id"] for row in rows]
        if not page_ids:
            return [{} for _ in terms]
        return [fetch(term, page_ids) for term in terms]
