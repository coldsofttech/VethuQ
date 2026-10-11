"""Searching indexed pages: `VethuQ().search`.

Search engines (`like`, `exact`, ...) and the normalizers they apply (`case`, `unicode`, ...) come
from add-ons. A search folds the query and each page's text alike with the normalizers that apply,
so highlights always show the original text. Only pages of files that are `indexed` are searched.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from vethuq._db import _Database
from vethuq._errors import _SearchOptionError
from vethuq._search import _Engines, _Search, _SearchIndex
from vethuq._search.service import _Match
from vethuq._settings import _SearchSettings
from vethuq.enums import SearchSortBy, SortOrder

__all__ = [
    "NormalizerInfo",
    "Search",
    "SearchEngineInfo",
    "SearchIndexStatus",
    "SearchMatch",
    "SearchResult",
    "SearchSortBy",
]


@dataclass(frozen=True)
class SearchMatch:
    """One occurrence of a query on a page, split around the match so it can be highlighted."""

    file_id: int  # the file's row in the index (`SourceFile.id`)
    document_id: int  # the document, shared by files with the same content
    file_name: str
    file_path: str
    page_number: int
    total_pages: int
    before: str
    matched: str  # the original text that matched
    after: str
    truncated_before: bool  # the text goes on before `before`
    truncated_after: bool
    duplicate_of_path: str | None  # set when the file has the same content as an earlier one
    source: str  # how the page's text was obtained: native, ocr or mixed
    score: float | None  # relevance, for engines that rank
    start: int  # where the match starts in the page's text (line breaks as spaces)
    end: int
    engine: str  # the strictest engine that found it
    matched_by: tuple[str, ...]  # every engine that found it, strictest first
    modifiers: tuple[str, ...]  # normalizations it needed to match as typed, e.g. `accents`

    @classmethod
    def _from(cls, match: _Match) -> SearchMatch:
        return cls(**asdict(match))

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["matched_by"] = list(self.matched_by)
        data["modifiers"] = list(self.modifiers)
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class SearchResult:
    """What a search found."""

    query: str
    engine: str  # `all`, or the engine that ran
    matches: list[SearchMatch]  # the page asked for (`limit`, `offset`)
    total: int  # how many matches there are in all
    levels: dict[str, dict[str, str]]  # per engine, the level each normalizer ran at
    index_rebuilt: bool = False  # the search index was rebuilt first (normalizers changed)

    def __iter__(self):
        return iter(self.matches)

    def __getitem__(self, index):
        return self.matches[index]

    def __len__(self) -> int:
        return len(self.matches)

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["matches"] = [m.to_dict() for m in self.matches]
        data["levels"] = {k: dict(v) for k, v in self.levels.items()}
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class NormalizerInfo:
    """A search normalizer: what counts as "the same character"."""

    id: str  # for example "case"
    levels: tuple[str, ...]
    identity: str  # the level that changes nothing
    version: str
    setting: str  # the saved level, or `auto`

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["levels"] = list(self.levels)
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class SearchEngineInfo:
    """A search engine."""

    id: str  # for example "like"
    label: str
    description: str
    available: bool
    reason: str  # why it can't be used, when it can't
    in_all: bool  # the `all` search includes it
    selected: bool  # it is the default engine
    normalizers: dict[str, str] = field(default_factory=dict)  # normalizer -> its default level

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class SearchIndexStatus:
    """The search index over the pages' text."""

    pages_indexed: int
    pages_total: int  # finished pages that should be in it
    current: bool  # it was built for the installed normalizers
    full_text: bool  # SQLite's trigram index is in use (otherwise searches scan the index)

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Search:
    """Search the indexed pages.

    Not created directly: use `VethuQ().search`.

        result = client.search.run("invoice")
        for match in result:
            print(match.file_path, match.page_number, match.before, match.matched, match.after)
    """

    def __init__(
        self, database: _Database, engines: _Engines, index: _SearchIndex, search: _Search
    ) -> None:
        self._database = database
        self._engines = engines
        self._index = index
        self._search = search

    def run(
        self,
        query: str,
        *,
        engine: str | None = None,
        normalize: Mapping[str, str] | str | None = None,
        case_sensitive: bool | None = None,
        context_chars: int | None = None,
        languages: str | Sequence[str] | None = None,
        sort: SearchSortBy | str = SearchSortBy.PATH,
        order: SortOrder | str = SortOrder.ASC,
        limit: int | None = None,
        offset: int = 0,
    ) -> SearchResult:
        """Find `query` on the indexed pages. An empty query matches nothing.

        `engine` is `all` (every engine that takes part, a hit marked with each that found it) or
        one engine's id; left out, the saved default (`settings.search`). `normalize` sets what
        counts as the same character, as `{"unicode": "full"}` or `"unicode=full,case=ignore"`;
        left out, the saved level of each normalizer, or the engine's own. `case_sensitive` is
        shorthand for `case=match` / `case=ignore`. `languages` keeps pages of documents read in
        those language ids (`"en"`). `limit` and `offset` page the result (`total` counts all).

        Raises `SearchUnavailableError` (unknown engine, or one that can't be used),
        `SearchOptionError` (an unknown normalizer or level, or one the engine can't change) and
        `SearchQueryError` (a query the engine can't search).
        """
        if not isinstance(query, str):
            raise TypeError("A query is text.")
        explicit = _Engines.parse(normalize)
        if case_sensitive is not None:
            wanted = "match" if case_sensitive else "ignore"
            if explicit.get("case", wanted) != wanted:
                raise _SearchOptionError(
                    "case_sensitive and normalize['case'] disagree.", option="case"
                )
            explicit["case"] = wanted
        try:
            sort_by, direction = SearchSortBy(sort), SortOrder(order)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise ValueError("limit is a whole number of 0 or more.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset is a whole number of 0 or more.")
        with self._database.session() as session:
            name = engine if engine is not None else _SearchSettings.get_engine(session)
            chars = (
                context_chars
                if context_chars is not None
                else _SearchSettings.get_context_chars(session)
            )
        if isinstance(languages, str):
            languages = [languages]
        outcome = self._search.run(
            query,
            name.strip().lower() if isinstance(name, str) else name,
            explicit,
            chars,
            list(languages) if languages is not None else None,
        )
        matches = outcome.matches
        if sort_by is SearchSortBy.SCORE:
            matches.sort(
                key=lambda m: (
                    m.score is None,
                    -(m.score or 0.0),
                    m.file_path,
                    m.page_number,
                    m.start,
                )
            )
        else:
            matches.sort(key=lambda m: (m.file_path, m.page_number, m.start))
        if direction is SortOrder.DESC:
            matches.reverse()
        total = len(matches)
        window = matches[offset : None if limit is None else offset + limit]
        return SearchResult(
            query=query,
            engine=outcome.engine,
            matches=[SearchMatch._from(m) for m in window],
            total=total,
            levels=outcome.levels,
            index_rebuilt=outcome.index_rebuilt,
        )

    def engines(self) -> list[SearchEngineInfo]:
        """The search engines add-ons provide, strictest first."""
        with self._database.session() as session:
            default = _SearchSettings.get_engine(session)
        return [
            SearchEngineInfo(
                id=view.id,
                label=view.spec.label,
                description=view.spec.description,
                available=view.available,
                reason=view.reason,
                in_all=view.spec.in_all,
                selected=view.id == default,
                normalizers={use.id: use.default for use in view.spec.normalizers},
            )
            for view in self._engines.views()
        ]

    def normalizers(self) -> list[NormalizerInfo]:
        """The search normalizers add-ons provide, in the order they apply."""
        with self._database.session() as session:
            return [
                NormalizerInfo(
                    id=n.id,
                    levels=tuple(n.levels),
                    identity=n.identity,
                    version=n.version,
                    setting=_SearchSettings.get_normalizer(session, n.id),
                )
                for n in self._engines.normalizers().values()
            ]

    def status(self) -> SearchIndexStatus:
        """How the search index stands. Looking never changes it."""
        indexed, total = self._index.counts()
        return SearchIndexStatus(indexed, total, self._index.is_current(), self._index.has_fts())

    def rebuild(self) -> int:
        """Throw the search index away and build it again from the stored page text. It is also
        rebuilt by itself when the installed normalizers change. Returns the pages indexed."""
        return self._index.rebuild()
