"""Searching indexed pages: `VethuQ().search`.

Search engines (`like`, `exact`, ...) and the normalizers they apply (`case`, `unicode`, ...) come
from add-ons. A search folds the query and each page's text alike with the normalizers that apply,
so highlights always show the original text. Only pages of files that are `indexed` are searched.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from sqlalchemy import text

from vethuq._db import _Database
from vethuq._errors import _IndexAlreadyRunningError, _SearchOptionError
from vethuq._export import _Exporter
from vethuq._filetypes.catalog import _FileTypeCatalog
from vethuq._indexing.runs import _Runs
from vethuq._search import HYBRID, _Engines, _Search, _SearchIndex
from vethuq._search.index import _Scope
from vethuq._search.service import _Match, _Synced
from vethuq._settings import _SearchSettings
from vethuq.enums import ExportFormat, SearchSortBy, SortOrder

__all__ = [
    "NormalizerInfo",
    "PageText",
    "Search",
    "SearchEngineInfo",
    "SearchIndexRebuildResult",
    "SearchIndexStatus",
    "SearchMatch",
    "SearchResult",
    "SearchSortBy",
    "SearchSyncReport",
]


@dataclass(frozen=True)
class PageText:
    """The text VethuQ stored for one page of a document: what searches ran against."""

    document_id: int
    page_number: int
    file_name: str
    file_path: str  # the earliest indexed file with this content
    file_type: str | None
    text: str


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
    file_type: str | None = None  # what the file is read as (`pdf`, `docx`, ...)
    # Where the match is in a plain-text file (text, CSV, TSV), counting from 1; None for files
    # whose pages are not the file's own lines (a PDF's page is `page_number`). For CSV and TSV the
    # line is the Nth non-empty row and the column counts in that row's indexed text (its
    # non-empty cells joined by " | "), not in the file's own row, which can have empty cells and
    # quoting.
    line: int | None = None
    column: int | None = None
    # Where on the picture the match was read, for a page read by OCR whose engine said where
    # (see `OcrResult.boxes`): one `(x0, y0, x1, y1)` for each line the match covers, as fractions
    # (0 to 1) of the image from its top-left corner. The part of a line the words take is worked
    # out from their share of its characters, so it is near, not exact. None when not known.
    boxes: tuple[tuple[float, float, float, float], ...] | None = None

    @classmethod
    def _from(cls, match: _Match) -> SearchMatch:
        data = asdict(match)
        data.pop("rank")
        return cls(**data)

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
    # Per engine, the pages it can't search yet because they aren't prepared (semantic search
    # embeds pages ahead of time: see `Search.sync`). Only engines with some are listed.
    pending: dict[str, int] = field(default_factory=dict)
    # The engine options this search was run with, by engine id (what `options=` asked for).
    options: dict[str, dict[str, str]] = field(default_factory=dict)

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
        data["pending"] = dict(self.pending)
        data["options"] = {k: dict(v) for k, v in self.options.items()}
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
    options: dict[str, str] = field(default_factory=dict)  # option -> its default
    approximate: bool = False  # it guesses (typos, meaning), so `rank` puts it below exact finds

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


_logger = logging.getLogger("vethuq.search")


@dataclass(frozen=True)
class SearchIndexRebuildResult:
    """What `search.rebuild()` did."""

    pages: int  # pages in the rebuilt index
    seconds: float
    error: str | None = None  # why it failed; None when it worked

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, object]:
        return {"pages": self.pages, "seconds": self.seconds, "ok": self.ok, "error": self.error}

    def to_json(self, indent: int | None = None) -> str:
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


@dataclass(frozen=True)
class SearchSyncReport:
    """What preparing one engine's pages did (`Search.sync`)."""

    engine: str
    pages: int  # prepared now
    pending: int  # still not prepared
    credits: float  # what it cost, in credits
    paused: bool  # it stopped because the engine's credits ran out; the next sync carries on
    message: str

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
        self,
        database: _Database,
        engines: _Engines,
        index: _SearchIndex,
        search: _Search,
        exporter: _Exporter,
        file_types: _FileTypeCatalog | None = None,
    ) -> None:
        self._file_types = file_types
        self._database = database
        self._engines = engines
        self._index = index
        self._search = search
        self._exporter = exporter

    def run(
        self,
        query: str,
        *,
        engine: str | None = None,
        normalize: Mapping[str, str] | str | None = None,
        case_sensitive: bool | None = None,
        context_chars: int | None = None,
        languages: str | Sequence[str] | None = None,
        file_types: str | Sequence[str] | None = None,
        sources: int | Sequence[int] | None = None,
        options: Mapping[str, Mapping[str, object]] | str | None = None,
        combine: str | None = None,
        sort: SearchSortBy | str | None = None,
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
        those language ids (`"en"`). `file_types` keeps files read as those types (`"pdf"` or
        `["pdf", "docx"]`, the ids of `client.file_types`) and `sources` keeps files of those
        sources (ids); a type or source that matches nothing gives no matches. `limit` and `offset`
        page the result (`total` counts all).

        `options` are engines' own settings for this search, by engine id: `{"fuzzy": {"threshold":
        0.7}}` or `"fuzzy.threshold=0.7"` (see `engines()` for what each takes). `engine="hybrid"`
        runs `semantic` together with a keyword engine (`combine`, `full-text` unless told) and
        ranks the pages both find by reciprocal rank fusion. `sort` is `path` (the default), `score`
        or `rank` (best match first across engines; the default for `hybrid`). Engines that
        prepare pages (semantic) only search the ones that are ready: `SearchResult.pending` says
        how many aren't (see `sync`).

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
            sort_by = SearchSortBy(sort) if sort is not None else None
            direction = SortOrder(order)
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
            saved = _SearchSettings.saved_options(session)
        if isinstance(languages, str):
            languages = [languages]
        scope = self._scope(file_types, sources)
        name = name.strip().lower() if isinstance(name, str) else name
        if combine is not None and not isinstance(combine, str):
            raise TypeError("combine is the id of a keyword engine.")
        asked = _Engines.parse_options(options)
        outcome = self._search.run(
            query,
            name,
            explicit,
            chars,
            list(languages) if languages is not None else None,
            asked,
            combine.strip().lower() if combine is not None else None,
            saved,
            scope,
        )
        matches = outcome.matches
        if sort_by is None:
            sort_by = SearchSortBy.RANK if name == HYBRID else SearchSortBy.PATH
        if sort_by is SearchSortBy.RANK:
            matches.sort(key=lambda m: m.rank)
        elif sort_by is SearchSortBy.SCORE:
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
            matches=self._located(window),
            total=total,
            levels=outcome.levels,
            index_rebuilt=outcome.index_rebuilt,
            pending=outcome.pending,
            options=asked,
        )

    # File types whose single page is the file's own lines, so a match has a line (and, except for
    # CSV and TSV whose fields are spread out, a column). HTML, XML and the like are read as
    # extracted text, whose lines are not the file's.
    LINE_TYPES = frozenset({"txt", "csv", "tsv"})

    def _located(self, window: list[_Match]) -> list[SearchMatch]:
        """The public matches of a page of results, each with its file type, the line and column
        where it sits in a plain-text file (text, CSV), and where on its picture it was read."""
        texts: dict[tuple[int, int], str] = {}
        placed: dict[tuple[int, int], list[tuple[str, float, float, float, float]]] = {}
        out = []
        with self._database.session() as session:

            def page_of(match: _Match) -> str:
                key = (match.document_id, match.page_number)
                if key not in texts:
                    texts[key] = (
                        session.execute(
                            text(
                                "SELECT text FROM pdf_pages WHERE document_id = :d "
                                "AND page_number = :p"
                            ),
                            {"d": match.document_id, "p": match.page_number},
                        ).scalar()
                        or ""
                    )
                return texts[key]

            def lines_of(match: _Match) -> list[tuple[str, float, float, float, float]]:
                key = (match.document_id, match.page_number)
                if key not in placed:
                    rows = session.execute(
                        text(
                            "SELECT b.text, b.x0, b.y0, b.x1, b.y1 FROM pdf_line_boxes b "
                            "JOIN pdf_pages p ON p.id = b.page_id WHERE p.document_id = :d "
                            "AND p.page_number = :p ORDER BY b.id"
                        ),
                        {"d": match.document_id, "p": match.page_number},
                    ).all()
                    placed[key] = [tuple(row) for row in rows]
                return placed[key]

            for match in window:
                file_type = self._file_type_of(match.file_path)
                line = column = None
                if file_type in self.LINE_TYPES:
                    before = page_of(match)[: match.start]
                    line = before.count("\n") + 1
                    column = match.start - (before.rfind("\n") + 1) + 1
                boxes = self._boxes(page_of, lines_of, match)
                out.append(
                    replace(
                        SearchMatch._from(match),
                        file_type=file_type,
                        line=line,
                        column=column,
                        boxes=boxes,
                    )
                )
        return out

    MAX_BOXES = 8

    @staticmethod
    def _boxes(page_of, lines_of, match: _Match):
        """Where on its picture a match was read: the box of each line it covers, narrowed to the
        share of the line its characters take. None when the page's lines were not placed."""
        read = lines_of(match)
        if not read:
            return None
        by_text: dict[str, tuple[float, float, float, float]] = {}
        for words, x0, y0, x1, y1 in read:
            by_text.setdefault(" ".join(words.split()), (x0, y0, x1, y1))
        found = []
        position = 0
        for line in page_of(match).split("\n"):
            end_of_line = position + len(line)
            if position < match.end and match.start <= end_of_line and line.strip():
                box = by_text.get(" ".join(line.split()))
                if box is not None and len(line) > 0:
                    x0, y0, x1, y1 = box
                    first = (max(match.start, position) - position) / len(line)
                    last = (min(match.end, end_of_line) - position) / len(line)
                    found.append(
                        (x0 + first * (x1 - x0), y0, x0 + max(last, first) * (x1 - x0), y1)
                    )
            position = end_of_line + 1
            if position > match.end:
                break
        return tuple(found[: Search.MAX_BOXES]) or None

    def _scope(
        self, file_types: str | Sequence[str] | None, sources: int | Sequence[int] | None
    ) -> _Scope | None:
        if file_types is None and sources is None:
            return None
        types = [file_types] if isinstance(file_types, str) else file_types
        if types is not None and not all(isinstance(t, str) for t in types):
            raise TypeError('file_types are file type ids such as "pdf".')
        ids = [sources] if isinstance(sources, int) and not isinstance(sources, bool) else sources
        if ids is not None and not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise TypeError("sources are source ids.")
        extensions = None
        if types is not None:
            wanted = {t.strip().lower() for t in types}
            specs = self._file_types.specs() if self._file_types is not None else []
            extensions = tuple(
                dict.fromkeys(e for s in specs if s.id in wanted for e in s.extensions)
            )
        return _Scope(extensions, tuple(ids) if ids is not None else None)

    def page_text(self, document_id: int, page_number: int = 1) -> PageText | None:
        """The text stored for a page of a document, as searches saw it (line breaks included), or
        None when there is no such page. For a text file the one page is the file's text, so a
        match's `line` and `column` count in it (Markdown's is the words without the markup)."""
        with self._database.session() as session:
            row = session.execute(
                text(
                    "SELECT d.file_path, p.text FROM pdf_pages p JOIN document_index d "
                    "ON d.document_id = p.document_id AND d.status = 'indexed' "
                    "WHERE p.document_id = :d AND p.page_number = :p ORDER BY d.id LIMIT 1"
                ),
                {"d": document_id, "p": page_number},
            ).first()
        if row is None:
            return None
        return PageText(
            document_id=document_id,
            page_number=page_number,
            file_name=Path(row.file_path).name,
            file_path=row.file_path,
            file_type=self._file_type_of(row.file_path),
            text=row.text or "",
        )

    def _file_type_of(self, path: str) -> str | None:
        """The id of the file type that reads `path` (None when no add-on does)."""
        spec = (
            self._file_types.for_path(path, include_disabled=True)
            if self._file_types is not None
            else None
        )
        return spec.id if spec is not None else None

    def export(
        self,
        result: SearchResult,
        output: str | Path,
        format: ExportFormat | str | None = None,
    ) -> Path:
        """Write a search result to a file and return its path.

        `format` is `json` or `html`; left out, the saved default (`settings.search`, `json`).
        The file holds the query, how the search was run (engine, the level each normalizer ran
        at, the engine options, the pages an engine hadn't prepared) and every match in
        `result.matches`: to export all of them, run the search without `limit`. The HTML is one
        portable page (logo, summary, a row per match that opens to its text, light and dark,
        printable); each match says how it was found (`Exact`, `Similar 83%`) and text in a
        language other than the default is marked up so a browser picks its font. The folder of
        `output` is created if needed.

        Raises `ValueError` for a format that isn't `json` or `html` and `IsADirectoryError` if
        `output` is a folder.
        """
        if not isinstance(result, SearchResult):
            raise TypeError("export takes the SearchResult that run() returned.")
        return self._exporter.search_results(result, Path(output), self._format(format))

    def _format(self, format_: ExportFormat | str | None) -> str:
        if format_ is None:
            with self._database.session() as session:
                return _SearchSettings.get_export_format(session)
        return _Exporter.check_format(str(getattr(format_, "value", format_)).strip().lower())

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
                normalizers={use.id: use.default for use in self._engines.uses(view)},
                options={option.name: option.default for option in view.spec.options},
                approximate=view.spec.approximate,
            )
            for view in self._engines.views()
        ]

    def sync(
        self,
        engine: str | None = None,
        *,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[SearchSyncReport]:
        """Prepare the pages for the engines that need it (semantic search embeds them), after
        bringing the search index up to date. `engine` is one engine's id (or `hybrid`); left out,
        every engine that is available is asked, and the ones with nothing to prepare answer with
        zeros. `progress(engine, done, total)` is called as pages are prepared.

        Preparing costs credits for the engines that charge (semantic search pays from its own
        credits, see `credits`); it stops, keeping what it did, when they run out
        (`SearchSyncReport.paused`), and the next call carries on. Searching never prepares
        anything and never charges.

        Raises `SearchUnavailableError` if a named engine isn't known, can't be used, or can't be
        prepared (for example its model can't be downloaded).
        """
        if engine is not None and not isinstance(engine, str):
            raise TypeError("engine is an engine id.")
        done = self._search.sync(engine.strip().lower() if engine is not None else None, progress)
        return [self._report(item) for item in done]

    @staticmethod
    def _report(item: _Synced) -> SearchSyncReport:
        return SearchSyncReport(
            engine=item.engine,
            pages=item.pages,
            pending=item.pending,
            credits=item.charged_milli / 1000,
            paused=item.paused,
            message=item.message,
        )

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

    def rebuild(self) -> SearchIndexRebuildResult:
        """Throw the search index away and build it again from the stored page text. No file is
        read again. It is also rebuilt by itself when the installed normalizers change.

        Raises `IndexAlreadyRunningError` while an index run is going. A failure is reported in
        the result (`ok` is False, `error` says why) rather than raised."""
        with self._database.session() as session:
            if _Runs.recover(session):
                raise _IndexAlreadyRunningError(
                    "An index run is going, so the search index can't be rebuilt now.",
                    "Wait for it to finish, then rebuild.",
                )
        started = time.monotonic()
        try:
            pages = self._index.rebuild()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            _logger.error("Search index rebuild failed: %s", exc)
            return SearchIndexRebuildResult(0, time.monotonic() - started, str(exc))
        seconds = time.monotonic() - started
        _logger.info("Search index rebuilt: %d pages in %.1fs", pages, seconds)
        return SearchIndexRebuildResult(pages, seconds)
