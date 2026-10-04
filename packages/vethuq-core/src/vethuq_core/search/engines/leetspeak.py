"""The `leetspeak` search engine: words written with look-alike character substitutions.

Finds `hello` in "h3ll0" and `password` in "p@55w0rd" - and the other way round,
`h3ll0` finds "hello". The substitutions come from a table kept here (nothing is stored
or configurable per user besides the level - see `SearchSettings.LEETSPEAK_LEVELS`):
each level knows more of them than the one before.

A query character and a page character match when they can stand for a common letter:
`3` and `e` both can be `e`, so they match each other; `1` can be `i` or `l`, so it
matches either. A match is whole words only (it can't start or end inside a longer
word), and spells every query character - there is no tolerance for typos, that's
`fuzzy`. Its score is the share of the query's characters that matched as typed, so a
page that spells the word out ranks above one that disguises it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from itertools import product
from string import ascii_letters, ascii_lowercase

from vethuq_core.search.engines.base import SearchMatch, SearchQueryError
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage

# Letter -> what it is written as, added at each level (cumulative).
_BASIC = {
    "a": ("4", "@"),
    "e": ("3",),
    "i": ("1",),
    "l": ("1",),
    "o": ("0",),
    "s": ("5", "$"),
    "t": ("7",),
}
_STANDARD = {
    "b": ("8",),
    "g": ("9", "6"),
    "i": ("!", "|"),
    "l": ("|",),
    "t": ("+",),
    "z": ("2",),
}
_EXTENDED = {
    "a": ("/\\",),
    "b": ("|3",),
    "c": ("(", "[", "{"),
    "d": ("|)",),
    "f": ("ph",),
    "h": ("|-|",),
    "k": ("|<",),
    "l": ("|_",),
    "m": ("/\\/\\",),
    "n": ("|\\|",),
    "o": ("()",),
    "r": ("|2",),
    "u": ("|_|",),
    "v": ("\\/",),
    "w": ("\\/\\/",),
}
_LEVEL_TABLES = {
    "basic": (_BASIC,),
    "standard": (_BASIC, _STANDARD),
    "extended": (_BASIC, _STANDARD, _EXTENDED),
}

# Most phrases the narrowing expression may hold; beyond that, every page is examined.
_MAX_NARROWING_PHRASES = 256
_NARROWING_WINDOW = 3  # units; the trigram index needs 3 characters


@dataclass(frozen=True)
class _Unit:
    """One thing a query spells: a letter or symbol, or a run of whitespace."""

    text: str
    pattern: str  # the regex that matches it, or any look-alike of it, on a page
    forms: tuple[str, ...]  # every spelling it matches (empty for whitespace)

    @property
    def is_space(self) -> bool:
        return not self.forms


class LeetspeakSearchEngine:
    """`SearchEngine` that finds query words disguised with look-alike characters.

    Whole words only, and the plain spelling matches too. Case-insensitive unless
    `case_sensitive`. Pages are ranked by how much of the query matched as typed
    (`SearchMatch.score`, 1.0 when none of it was substituted), then by file path
    and page. At least three characters are needed, one of them a letter.
    """

    name = "leetspeak"

    MIN_CHARS = 3

    def __init__(self, storage: Storage, level: str | None = None) -> None:
        self._storage = storage
        self._level = level

    def search(
        self,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
    ) -> list[SearchMatch]:
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        SearchEngineHelpers.require_no_distance(self.name, distance)
        query = query.strip()
        if not query:
            return []
        units = LeetspeakSearchEngine._units(
            query,
            SearchSettings.get_leetspeak_level(self._storage)
            if self._level is None
            else SearchSettings.parse_leetspeak_level(self._level),
            case_sensitive,
        )
        spelled = [unit for unit in units if not unit.is_space]
        if len(spelled) < LeetspeakSearchEngine.MIN_CHARS:
            raise SearchQueryError(
                f"The leetspeak engine needs at least {LeetspeakSearchEngine.MIN_CHARS} "
                "characters; use the like engine for shorter queries."
            )
        if not any(char.isalpha() for char in query):
            return []  # nothing to substitute: digits and symbols are what `like` is for

        pattern = re.compile(
            r"(?<!\w)" + "".join(f"({unit.pattern})" for unit in units) + r"(?!\w)",
            0 if case_sensitive else re.IGNORECASE,
        )
        expression = LeetspeakSearchEngine.narrowing_expression(units)
        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        ranked: list[tuple[float, str, int, list[SearchMatch]]] = []
        for row in (
            *self._storage.search_candidate_pdf_pages(expression),
            *self._storage.search_candidate_image_pages(expression),
        ):
            text = row["ocr_text"].replace("\n", " ")
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
                    start=found.start(),
                    end=found.end(),
                    chars=chars,
                    engine=self.name,
                    score=LeetspeakSearchEngine._score(found, spelled, units, case_sensitive),
                )
                for found in pattern.finditer(text)
            ]
            if page_matches:
                best = max(match.score or 0.0 for match in page_matches)
                ranked.append((best, row["file_path"], page_number or 0, page_matches))

        ranked.sort(key=lambda page: (-page[0], page[1], page[2]))
        return [match for *_, page_matches in ranked for match in page_matches]

    @staticmethod
    def _score(
        found: re.Match[str], spelled: list[_Unit], units: list[_Unit], case_sensitive: bool
    ) -> float:
        """The share of the query's characters `found` spells as typed (1.0 for all of them)."""
        as_typed = 0
        for index, unit in enumerate(units, start=1):
            if unit.is_space:
                continue
            page = found.group(index)
            if page == unit.text or (not case_sensitive and page.lower() == unit.text.lower()):
                as_typed += 1
        return as_typed / len(spelled)

    @staticmethod
    def _units(query: str, level: str, case_sensitive: bool) -> list[_Unit]:
        """Split `query` into units, reading a multi-character spelling (`|\\|`) as one."""
        spellings = LeetspeakSearchEngine._spellings(level, case_sensitive)
        longest = max(len(spelling) for spelling in spellings)
        units: list[_Unit] = []
        position = 0
        while position < len(query):
            if query[position].isspace():
                end = position
                while end < len(query) and query[end].isspace():
                    end += 1
                units.append(_Unit(query[position:end], r"\s+", ()))
                position = end
                continue
            size = next(
                (
                    n
                    for n in range(min(longest, len(query) - position), 0, -1)
                    if LeetspeakSearchEngine._key(query[position : position + n], case_sensitive)
                    in spellings
                ),
                1,
            )
            text = query[position : position + size]
            units.append(LeetspeakSearchEngine._unit(text, level, case_sensitive))
            position += size
        return units

    @staticmethod
    def _key(text: str, case_sensitive: bool) -> str:
        return text if case_sensitive else text.lower()

    @staticmethod
    @cache
    def _spellings(level: str, case_sensitive: bool) -> dict[str, frozenset[str]]:
        """Every leet spelling known at `level` -> the letters it can stand for."""
        spellings: dict[str, set[str]] = {}
        for table in _LEVEL_TABLES[level]:
            for letter, written in table.items():
                letters = {letter, letter.upper()} if case_sensitive else {letter}
                for spelling in written:
                    spellings.setdefault(spelling, set()).update(letters)
        return {spelling: frozenset(letters) for spelling, letters in spellings.items()}

    @staticmethod
    @cache
    def _unit(text: str, level: str, case_sensitive: bool) -> _Unit:
        """The unit for one spelling `text`: every spelling that can mean what it means."""
        spellings = LeetspeakSearchEngine._spellings(level, case_sensitive)
        key = LeetspeakSearchEngine._key(text, case_sensitive)
        meaning = {key} | spellings.get(key, frozenset())
        letters = ascii_letters if case_sensitive else ascii_lowercase
        forms = {text} | {
            form
            for form in (*letters, *spellings)
            if ({form} | spellings.get(form, frozenset())) & meaning
        }
        ordered = tuple(sorted(forms, key=lambda form: (-len(form), form)))
        return _Unit(text, "|".join(re.escape(form) for form in ordered), ordered)

    @staticmethod
    def narrowing_expression(units: list[_Unit]) -> str | None:
        """An FTS5 expression over the trigram index that every page matching `units` satisfies.

        Only used to skip pages that can't match; the regular expression has the final
        say. Any three consecutive characters of the query are written, on a matching
        page, as one of a handful of spellings, so the page contains one of them: the
        expression lists them all, for the window with the fewest. Returns None when
        there are too many to be worth it (every page is then examined).
        """
        best: list[str] | None = None
        for start in range(len(units) - _NARROWING_WINDOW + 1):
            window = units[start : start + _NARROWING_WINDOW]
            if any(unit.is_space for unit in window):
                continue
            size = 1
            for unit in window:
                size *= len(unit.forms)
            if size > _MAX_NARROWING_PHRASES or (best is not None and size >= len(best)):
                continue
            best = ["".join(spelling) for spelling in product(*(unit.forms for unit in window))]
        if best is None:
            return None
        return " OR ".join('"' + phrase.replace('"', '""') + '"' for phrase in best)
