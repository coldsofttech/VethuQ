"""The `full-text` search engine: whole-word, stemmed, relevance-ranked matching."""

from __future__ import annotations

import re

from vethuq_core.languages import Scripts
from vethuq_core.search.engines.base import SearchEngineUnavailable, SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.storage import Storage


class FullTextSearchEngine:
    """`SearchEngine` that finds pages containing the query's words, ranked by relevance (BM25).

    Word-based rather than substring-based: `museum` finds "Museum" and
    "museums" (case is folded and English words stemmed) but `mus` doesn't
    unless written as the prefix `mus*`. Results are ordered best first -
    `SearchMatch.score` - with one match per matched word or phrase on a page.
    The index folds case, so this engine can't match case-sensitively.

    A query with Telugu in it (any script whose marks are part of its words) is looked up in the
    mark-aware word index instead, which keeps `అమ్మ` whole where the plain one splits it at its
    vowel signs. That index does not stem, so Telugu words match as written (or as a prefix,
    `ఇంట*`), and a mixed query matches its English words unstemmed too.
    """

    name = "full-text"

    # Highlight markers - see `Document.search_fulltext_pdf_pages`.
    _OPEN, _CLOSE = "\x02", "\x03"
    _TERM = re.compile(r'"([^"]*)"|(\S+)')
    _WORDS = Scripts.word_pattern()
    _HIGHLIGHT = re.compile(f"{_OPEN}(.*?){_CLOSE}", re.DOTALL)

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
        SearchEngineHelpers.require_no_unicode(self.name, unicode)
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        if case_sensitive:
            raise ValueError("The full-text engine is always case-insensitive.")
        expression = FullTextSearchEngine.build_match_expression(query)
        if expression is None:
            return []
        complex_index = FullTextSearchEngine.needs_mark_aware_index(self._storage, query)

        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        matches: list[SearchMatch] = []
        for row in (
            *self._storage.search_fulltext_pdf_pages(expression, complex_index),
            *self._storage.search_fulltext_image_pages(expression, complex_index),
        ):
            page_number = row["page_number"]
            # Newlines flatten to spaces, one-for-one, so the spans stay valid.
            text, spans = FullTextSearchEngine._highlighted_spans(
                row["highlighted_text"].replace("\n", " ")
            )
            total_pages = page_counts.get(row["canonical_id"]) if page_number is not None else None
            for start, end in spans:
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

    @staticmethod
    def needs_mark_aware_index(storage: Storage, query: str) -> bool:
        """Whether `query` has to be looked up in the mark-aware word index (it has Telugu in it).

        Raises `SearchEngineUnavailable` if that index does not exist, which is when this
        SQLite is too old for the tokenizer it needs: Telugu words can't be searched here, and
        silently searching the plain index would match consonant fragments instead.
        """
        if not Scripts.has_mark_script(query):
            return False
        if not storage.has_complex_word_index():
            raise SearchEngineUnavailable(
                "Telugu word search needs a newer SQLite than this one; "
                "the 'like' and 'fuzzy' engines still find Telugu text."
            )
        return True

    @staticmethod
    def parse_terms(query: str) -> list[str]:
        """Split a user's `query` into safe FTS5 term expressions, one per word or phrase.

        A `"double quoted"` run is a phrase (its words adjacent, in order), a term
        ending in `*` is a prefix (`mus*` finds "museum"), and anything else is a
        whole word. Each term is reduced to its word characters and quoted, so
        punctuation and FTS5 operators (`AND`, `NEAR`, `-`, `:` ...) in the query
        are searched as plain text and never interpreted. Terms with no word
        characters are dropped.
        """
        terms = []
        for phrase, bare in FullTextSearchEngine._TERM.findall(query):
            words = FullTextSearchEngine._WORDS.findall(phrase or bare)
            if not words:
                continue
            expr = '"' + " ".join(words) + '"'
            if bare.endswith("*"):
                expr += " *"
            terms.append(expr)
        return terms

    @staticmethod
    def build_match_expression(query: str) -> str | None:
        """Turn a user's `query` into a safe FTS5 `MATCH` expression, or None if it has no words.

        Every term (see `parse_terms`) must appear on the page (AND).
        """
        terms = FullTextSearchEngine.parse_terms(query)
        return " ".join(terms) if terms else None

    @staticmethod
    def _highlighted_spans(highlighted: str) -> tuple[str, list[tuple[int, int]]]:
        """Split FTS5-highlighted text into its plain text and the `(start, end)` of each hit."""
        plain: list[str] = []
        spans: list[tuple[int, int]] = []
        length = 0
        cursor = 0
        for hit in FullTextSearchEngine._HIGHLIGHT.finditer(highlighted):
            before = highlighted[cursor : hit.start()]
            plain.append(before)
            length += len(before)
            matched = hit.group(1)
            spans.append((length, length + len(matched)))
            plain.append(matched)
            length += len(matched)
            cursor = hit.end()
        plain.append(highlighted[cursor:])
        return "".join(plain), spans
