"""The `like` search engine: substring matching over OCR text, mid-word included."""

from __future__ import annotations

from collections.abc import Iterator

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.normalizers import Leet, Normalizers
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class LikeSearchEngine:
    """`SearchEngine` that finds `query` as a substring anywhere in a page's text.

    Case-insensitive unless `case_sensitive` is set, and not word-aware: `mus`
    finds "Museum" and `arge` finds "large". Occurrences don't overlap.

    With a leetspeak `level` (the `leetspeak` normalizer; off unless the setting or the argument
    says otherwise) look-alike characters count as the letters they stand for, in the query and
    on the page: `hello` finds "h3ll0" and `p@55w0rd` finds "password". `SearchMatch.score` is
    then the share of the query's characters the match has as typed (1.0 when none was a
    look-alike). A query too short or letterless to have look-alikes (under 3 characters, or
    only digits and symbols) is searched as it is.
    """

    name = "like"

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
        SearchEngineHelpers.require_no_noise(self.name, noise)
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        lookalikes = (
            SearchSettings.resolve_leetspeak(self._storage, SearchSettings.LEETSPEAK_OFF)
            if level is None
            else SearchSettings.parse_leetspeak(level)
        )
        if lookalikes != SearchSettings.LEETSPEAK_OFF and not LikeSearchEngine.has_lookalikes(
            query
        ):
            lookalikes = SearchSettings.LEETSPEAK_OFF
        folding = (
            SearchSettings.resolve_unicode(self._storage, SearchSettings.DEFAULT_UNICODE)
            if unicode is None
            else SearchSettings.parse_unicode(unicode)
        )
        if lookalikes != SearchSettings.LEETSPEAK_OFF or folding != "off":
            return self._search_normalized(
                query, context_chars, case_sensitive, lookalikes, folding
            )
        return SearchEngineHelpers.search_substring_pages(
            self._storage,
            query,
            lambda text: LikeSearchEngine._occurrences(text, query, case_sensitive=case_sensitive),
            context_chars=context_chars,
            engine=self.name,
        )

    MIN_LOOKALIKE_CHARS = 3

    @staticmethod
    def has_lookalikes(query: str) -> bool:
        """Whether `query` is one look-alikes make sense for: three characters or more, a
        letter among them (`2024` and `007` are numbers, not disguised words)."""
        spelled = [char for char in query if not char.isspace()]
        return len(spelled) >= LikeSearchEngine.MIN_LOOKALIKE_CHARS and any(
            char.isalpha() for char in spelled
        )

    def _search_normalized(
        self,
        query: str,
        context_chars: int | None,
        case_sensitive: bool,
        level: str,
        unicode: str,
    ) -> list[SearchMatch]:
        """`query` as a substring, with Unicode and look-alike normalization applied to it and
        to the page text alike (see `Normalizers.pipeline`).

        With look-alikes, candidate pages come from the trigram index over each page's recorded
        skeleton (its text without noise, look-alikes folded as coarsely as any level does),
        which every page that has the folded query holds. A Unicode normalization changes what
        the page text is, which that index (made of the raw text) can't know, so every page is
        a candidate. The folded text has the final say.
        """
        pipeline = Normalizers.pipeline(
            {
                "unicode": unicode,
                "case": "match" if case_sensitive else "ignore",
                "leetspeak": level,
            }
        )
        needle = pipeline.fold(query).text
        if not needle:
            return []
        narrowed = unicode == "off" and level != SearchSettings.LEETSPEAK_OFF
        expression = SearchEngineHelpers.trigram_match(Leet.skeleton(query)) if narrowed else None
        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        matches: list[SearchMatch] = []
        for row in (
            *self._storage.search_noise_candidate_pdf_pages(expression),
            *self._storage.search_noise_candidate_image_pages(expression),
        ):
            text = row["ocr_text"].replace("\n", " ")
            folded = pipeline.fold(text)
            page_number = row["page_number"]
            total_pages = page_counts.get(row["canonical_id"]) if page_number is not None else None
            for start, end in LikeSearchEngine._occurrences(
                folded.text, needle, case_sensitive=True
            ):
                start, end = folded.original(start, end)
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
                        score=(
                            LikeSearchEngine._as_typed(query, text[start:end], case_sensitive)
                            if level != SearchSettings.LEETSPEAK_OFF
                            else None
                        ),
                    )
                )
        matches.sort(key=lambda m: (m.file_path, m.page_number or 0, m.start or 0))
        return matches

    @staticmethod
    def _as_typed(query: str, matched: str, case_sensitive: bool) -> float:
        """The share of `query`'s characters `matched` has as typed (1.0 for all of them)."""
        if case_sensitive:
            same = sum(a == b for a, b in zip(query, matched, strict=False))
        else:
            same = sum(a.lower() == b.lower() for a, b in zip(query, matched, strict=False))
        return same / len(query) if query else 1.0

    @staticmethod
    def _occurrences(text: str, query: str, *, case_sensitive: bool) -> Iterator[tuple[int, int]]:
        """Yield the non-overlapping `(start, end)` spans of `query` in `text`."""
        haystack, needle = (text, query) if case_sensitive else (text.lower(), query.lower())
        position = haystack.find(needle)
        while position != -1:
            end = position + len(query)
            yield position, end
            position = haystack.find(needle, end)
