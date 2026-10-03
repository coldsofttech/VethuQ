"""The `exact` search engine: case-sensitive, whole-word matching of the query as typed."""

from __future__ import annotations

import re

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.storage import Storage


class ExactSearchEngine:
    """`SearchEngine` that finds `query` exactly - same characters, same case, as a whole word.

    `Museum` finds "Museum" but not "museum" or "Museums", and `mus` finds
    neither. Always case-sensitive, so `case_sensitive` has no effect.
    """

    name = "exact"

    _WORD_CHAR = re.compile(r"\w")

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def search(
        self, query: str, *, context_chars: int | None = None, case_sensitive: bool = False
    ) -> list[SearchMatch]:
        if not query:
            return []
        pattern = ExactSearchEngine._exact_pattern(query)
        return SearchEngineHelpers.search_substring_pages(
            self._storage,
            query,
            lambda text: ((m.start(), m.end()) for m in pattern.finditer(text)),
            context_chars=context_chars,
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
