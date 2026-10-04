"""The `exact` search engine: case-sensitive, whole-word matching of the query as typed."""

from __future__ import annotations

import re
from collections.abc import Iterator

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.normalizers import Normalizers
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class ExactSearchEngine:
    """`SearchEngine` that finds `query` exactly - same characters, same case, as a whole word.

    `Museum` finds "Museum" but not "museum" or "Museums", and `mus` finds
    neither. Always case-sensitive, so `case_sensitive` has no effect. It takes a Unicode level
    (`basic` or `full`) only when asked for, never from the stored setting: "as typed" stays
    as typed unless you say otherwise.
    """

    name = "exact"

    _WORD_CHAR = re.compile(r"\w")

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
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        if not query:
            return []
        folding = (
            SearchSettings.UNICODE_DEFAULTS[self.name]
            if unicode is None
            else SearchSettings.parse_unicode(unicode)
        )
        if folding != "off":
            pipeline = Normalizers.pipeline({"unicode": folding})
            needle = pipeline.fold(query).text
            if not needle:
                return []
            folded_pattern = ExactSearchEngine._exact_pattern(needle)

            def find_folded(text: str) -> Iterator[tuple[int, int]]:
                folded = pipeline.fold(text)
                for found in folded_pattern.finditer(folded.text):
                    yield folded.original(found.start(), found.end())

            return SearchEngineHelpers.search_substring_pages(
                self._storage,
                query,
                find_folded,
                context_chars=context_chars,
                engine=self.name,
                candidates="norm",
            )
        pattern = ExactSearchEngine._exact_pattern(query)
        return SearchEngineHelpers.search_substring_pages(
            self._storage,
            query,
            lambda text: ((m.start(), m.end()) for m in pattern.finditer(text)),
            context_chars=context_chars,
            engine=self.name,
        )

    @staticmethod
    def _exact_pattern(query: str) -> re.Pattern[str]:
        """Regex matching `query` literally, not glued to a neighbouring word character.

        The boundary is only enforced on a side where the query itself starts/ends
        with a word character, so `$1,200.00` (which ends in a digit but starts
        with a symbol) still matches right after other text on its left.
        """
        before = r"(?<!\w)" if ExactSearchEngine._WORD_CHAR.match(query[0]) else ""
        after = r"(?!\w)" if ExactSearchEngine._WORD_CHAR.match(query[-1]) else ""
        return re.compile(f"{before}{re.escape(query)}{after}")
