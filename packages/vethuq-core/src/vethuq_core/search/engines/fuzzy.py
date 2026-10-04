"""The `fuzzy` search engine: whole words within a similarity threshold of the query's words.

Tolerates the misspellings and OCR misreads the other engines can't: `Musuem`,
`Muzeum` and `Museurn` all find "Museum". It works a word at a time - every
query word must be matched on a page, each by a page word that is at least
`threshold` similar to it.

Similarity is `1 - distance / length of the longer word`, where `distance` is
the optimal-string-alignment edit distance (insert, delete, substitute or swap
two neighbours, each one edit). Guard rails keep it from becoming noise:

* words shorter than `MIN_FUZZY_LENGTH`, and any word containing a digit
  (identifiers, amounts, dates), match exactly - a near-miss there is a
  different thing, not a typo;
* at most `MAX_EDITS` edits, however long the word or loose the threshold.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.normalizers import Normalizers
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class FuzzySearchEngine:
    """`SearchEngine` that finds pages whose words are close to the query's, best first.

    Every query word must be matched. Results are ordered by how close a page's
    matches are (`SearchMatch.score` is each word's similarity, 1.0 for an
    identical word), then by file path and page. Case-insensitive unless
    `case_sensitive`. See the module docstring for what counts as close.
    """

    name = "fuzzy"

    MIN_FUZZY_LENGTH = 4
    MAX_EDITS = 2

    _WORD = re.compile(r"\w+")
    # So 0.8 accepts 4 letters with 1 edit (1 - 1/5 == 0.8 in floating point).
    _TOLERANCE = 1e-9

    @dataclass(frozen=True)
    class _Hit:
        start: int
        end: int
        score: float

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
        unicode: str | None = None,
    ) -> list[SearchMatch]:
        SearchEngineHelpers.require_no_level(self.name, level)
        SearchEngineHelpers.require_no_noise(self.name, noise)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        folding = (
            SearchSettings.resolve_unicode(
                self._storage, SearchSettings.UNICODE_DEFAULTS[self.name]
            )
            if unicode is None
            else SearchSettings.parse_unicode(unicode)
        )
        pipeline = Normalizers.pipeline({"unicode": folding}) if folding != "off" else None
        limit = (
            SearchSettings.get_fuzzy_threshold(self._storage)
            if threshold is None
            else SearchSettings.parse_fuzzy_threshold(threshold)
        )
        words = [
            w if case_sensitive else w.casefold()
            for w in FuzzySearchEngine._WORD.findall(
                pipeline.fold(query).text if pipeline else query
            )
        ]
        words = list(dict.fromkeys(words))
        if not words:
            return []

        # The norm index holds each page's text folded as coarsely as any normalization does,
        # and a fold never adds edits between two words, so the query's folded words narrow it.
        expression = FuzzySearchEngine.narrowing_expression(
            (Normalizers.index_form(w) for w in words), limit
        )
        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        ranked: list[tuple[float, str, int, list[SearchMatch]]] = []
        for row in (
            *self._storage.search_norm_candidate_pdf_pages(expression),
            *self._storage.search_norm_candidate_image_pages(expression),
        ):
            text = row["ocr_text"].replace("\n", " ")
            folded = pipeline.fold(text) if pipeline else None
            found = FuzzySearchEngine._page_hits(
                folded.text if folded else text, words, limit, case_sensitive
            )
            if found is None:
                continue
            hits, page_score = found
            if folded is not None:
                hits = [
                    FuzzySearchEngine._Hit(*folded.original(hit.start, hit.end), hit.score)
                    for hit in hits
                ]
            page_number = row["page_number"]
            total_pages = page_counts.get(row["canonical_id"]) if page_number is not None else None
            page_matches = [
                SearchEngineHelpers.build_match(
                    document_id=row["document_id"],
                    file_path=row["file_path"],
                    page_number=page_number,
                    total_pages=total_pages,
                    duplicate_of_path=row["duplicate_of_path"],
                    source=row["source"],
                    text=text,
                    start=hit.start,
                    end=hit.end,
                    chars=chars,
                    engine=self.name,
                    score=hit.score,
                )
                for hit in hits
            ]
            ranked.append((page_score, row["file_path"], page_number or 0, page_matches))

        ranked.sort(key=lambda page: (-page[0], page[1], page[2]))
        return [match for *_, page_matches in ranked for match in page_matches]

    @staticmethod
    def edit_distance(a: str, b: str, limit: int) -> int:
        """Optimal-string-alignment distance of `a` and `b`, or `limit + 1` if above `limit`."""
        if abs(len(a) - len(b)) > limit:
            return limit + 1
        previous_previous: list[int] = []
        previous = list(range(len(b) + 1))
        for i, char_a in enumerate(a, start=1):
            current = [i] + [0] * len(b)
            for j, char_b in enumerate(b, start=1):
                cost = 0 if char_a == char_b else 1
                current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
                if i > 1 and j > 1 and char_a == b[j - 2] and a[i - 2] == char_b:
                    current[j] = min(current[j], previous_previous[j - 2] + 1)
            # A swap reaches two rows back, so both recent rows must be over the limit.
            if min(current) > limit and min(previous) > limit:
                return limit + 1
            previous_previous, previous = previous, current
        return min(previous[-1], limit + 1)

    @staticmethod
    def similarity(query_word: str, page_word: str, threshold: float) -> float | None:
        """How similar `page_word` is to `query_word` (0-1), or None if it's below `threshold`."""
        if query_word == page_word:
            return 1.0
        if len(query_word) < FuzzySearchEngine.MIN_FUZZY_LENGTH or any(
            c.isdigit() for c in query_word
        ):
            return None
        longest = max(len(query_word), len(page_word))
        distance = FuzzySearchEngine.edit_distance(
            query_word, page_word, FuzzySearchEngine.MAX_EDITS
        )
        if distance > FuzzySearchEngine.MAX_EDITS:
            return None
        score = 1 - distance / longest
        return score if score >= threshold - FuzzySearchEngine._TOLERANCE else None

    @staticmethod
    def narrowing_expression(words: Iterable[str], threshold: float) -> str | None:
        """An FTS5 expression over the trigram index that every page matching `words` satisfies.

        Only used to skip pages that can't match; `similarity` has the final say,
        so it may let non-matches through but must never drop a match. Returns None
        when no word can be narrowed soundly (every page is then examined). Per word:

        * a word matched exactly must appear as a substring: `"word"`;
        * a fuzzy word of `n` letters within `k` edits shares at least one of its
          `n - 2` trigrams with any match as long as `n - 2 > 3k` (one edit spoils at
          most three trigrams), so any of them will do: `("abc" OR "bcd" ...)`.

        Words are `\\w+` only, so nothing here needs escaping.
        """
        groups = []
        for word in words:
            if len(word) < FuzzySearchEngine.MIN_FUZZY_LENGTH or any(c.isdigit() for c in word):
                if len(word) >= 3:
                    groups.append(f'"{word}"')
                continue
            longest = len(word) + FuzzySearchEngine.MAX_EDITS
            edits = min(
                FuzzySearchEngine.MAX_EDITS,
                int((1 - threshold) * longest + FuzzySearchEngine._TOLERANCE),
            )
            if len(word) - 2 > 3 * edits:
                trigrams = sorted({word[i : i + 3] for i in range(len(word) - 2)})
                groups.append("(" + " OR ".join(f'"{t}"' for t in trigrams) + ")")
        return " AND ".join(groups) if groups else None

    @staticmethod
    def _page_hits(
        text: str, query_words: list[str], threshold: float, case_sensitive: bool
    ) -> tuple[list[_Hit], float] | None:
        """The fuzzy hits on a page, in text order, and the page's score - or None if not every
        query word is matched. The page score is the mean, over query words, of the best
        similarity each achieved."""
        best = dict.fromkeys(query_words, 0.0)
        hits: list[FuzzySearchEngine._Hit] = []
        cache: dict[tuple[str, str], float | None] = {}
        for found in FuzzySearchEngine._WORD.finditer(text):
            word = found.group() if case_sensitive else found.group().casefold()
            best_for_word = 0.0
            for query_word in query_words:
                key = (query_word, word)
                if key not in cache:
                    cache[key] = FuzzySearchEngine.similarity(query_word, word, threshold)
                score = cache[key]
                if score is not None:
                    best[query_word] = max(best[query_word], score)
                    best_for_word = max(best_for_word, score)
            if best_for_word:
                hits.append(FuzzySearchEngine._Hit(found.start(), found.end(), best_for_word))
        if not all(best.values()):
            return None
        return hits, sum(best.values()) / len(best)
