"""Running a search: choosing the engines and their levels, bringing the index up to date, asking
each engine for its hits on the candidate pages, and turning hits into matches in files."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from vethuq._db import _Database
from vethuq._errors import _SearchOptionError, _SearchQueryError
from vethuq._search.engines import ALL, _Engines, _EngineView
from vethuq._search.index import _SearchIndex
from vethuq_addon_api import AddonError, Hit, PageText, SearchCorpus, SearchRequest

_logger = logging.getLogger("vethuq.search")


class _Corpus(SearchCorpus):
    """The pages a search runs over: searchable documents' finished pages, narrowed by the index."""

    def __init__(self, index: _SearchIndex, languages: Sequence[int] | None, use_fts: bool) -> None:
        self._index = index
        self._languages = languages
        self._use_fts = use_fts

    def candidates(self, query: str | None = None) -> Iterator[PageText]:
        after, totals = 0, {}
        while True:
            with self._index.database.session() as session:
                rows = self._index.candidate_rows(
                    session, query, after, self._languages, self._use_fts
                )
                for row in rows:
                    if row.document_id not in totals:
                        totals[row.document_id] = self._index.page_count(session, row.document_id)
            for row in rows:
                yield PageText(
                    page_id=row.id,
                    document_id=row.document_id,
                    page_number=row.page_number,
                    total_pages=totals[row.document_id],
                    text=row.text.replace("\n", " "),
                    source=str(row.source),
                )
            if len(rows) < self._index.BATCH:
                return
            after = rows[-1].id


@dataclass
class _Match:
    file_id: int
    document_id: int
    file_name: str
    file_path: str
    page_number: int
    total_pages: int
    before: str
    matched: str
    after: str
    truncated_before: bool
    truncated_after: bool
    duplicate_of_path: str | None
    source: str
    score: float | None
    start: int
    end: int
    engine: str
    matched_by: tuple[str, ...]
    modifiers: tuple[str, ...]


@dataclass
class _Outcome:
    engine: str
    matches: list[_Match]
    levels: dict[str, dict[str, str]]
    index_rebuilt: bool


class _Search:
    DEFAULT_ENGINE = ALL

    def __init__(self, database: _Database, engines: _Engines, index: _SearchIndex) -> None:
        self.database = database
        self.engines = engines
        self.index = index

    def language_ids(self, codes: Sequence[str] | None) -> list[int] | None:
        if codes is None:
            return None
        if not codes:
            return []
        marks = ",".join(f":c{i}" for i in range(len(codes)))
        with self.database.session() as session:
            rows = session.execute(
                text(f"SELECT id FROM languages WHERE language IN ({marks})"),  # noqa: S608 - fixed names and bound values
                {f"c{i}": code for i, code in enumerate(codes)},
            ).all()
        return [row.id for row in rows]

    def run(
        self,
        query: str,
        engine: str,
        explicit: Mapping[str, str],
        context_chars: int,
        languages: Sequence[str] | None,
    ) -> _Outcome:
        chosen = self.engines.choose(engine)
        self.engines.check_explicit(explicit)
        strict = engine != ALL
        if not strict:
            used = {use.id for view in chosen for use in view.spec.normalizers}
            for name in explicit:
                if name not in used:
                    raise _SearchOptionError(
                        f"No search engine uses the {name} normalizer.", option=name
                    )
        levels = {view.id: self.engines.levels(view, explicit, strict=strict) for view in chosen}
        if not query.strip():
            return _Outcome(engine, [], levels, False)
        _count, rebuilt = self.index.sync()
        language_ids = self.language_ids(languages)
        corpus = _Corpus(self.index, language_ids, self.index.has_fts())
        found: dict[tuple[int, int, int, int], list[tuple[_EngineView, Hit]]] = {}
        for view in chosen:
            request = SearchRequest(query, self.engines.pipeline(levels[view.id]))
            try:
                for hit in view.spec.engine.search(request, corpus):  # type: ignore[union-attr]
                    key = (hit.page.document_id, hit.page.page_number, hit.start, hit.end)
                    found.setdefault(key, []).append((view, hit))
            except AddonError as exc:
                if strict:
                    raise _SearchQueryError(str(exc)) from exc
                _logger.info("The %s engine can't search this query: %s", view.id, exc)
            except Exception:  # noqa: BLE001 - one broken engine never spoils an `all` search
                if strict:
                    raise
                _logger.warning("The %s engine failed", view.id, exc_info=True)
        return _Outcome(engine, self._matches(found, context_chars), levels, rebuilt)

    # ----- matches ----------------------------------------------------------------------------

    def _files(self, document_ids: set[int]) -> dict[int, list[tuple[int, str]]]:
        """The searchable files of each document, the original first."""
        if not document_ids:
            return {}
        ids = sorted(document_ids)
        files: dict[int, list[tuple[int, str]]] = {}
        with self.database.session() as session:
            for start in range(0, len(ids), 400):
                chunk = ids[start : start + 400]
                marks = ",".join(f":d{i}" for i in range(len(chunk)))
                rows = session.execute(
                    text(
                        "SELECT id, document_id, file_path FROM document_index "  # noqa: S608 - fixed names and bound values
                        f"WHERE status = 'indexed' AND document_id IN ({marks}) ORDER BY id"
                    ),
                    {f"d{i}": d for i, d in enumerate(chunk)},
                ).all()
                for row in rows:
                    files.setdefault(row.document_id, []).append((row.id, row.file_path))
        return files

    def _matches(
        self, found: dict[tuple[int, int, int, int], list[tuple[_EngineView, Hit]]], chars: int
    ) -> list[_Match]:
        files = self._files({key[0] for key in found})
        matches: list[_Match] = []
        for hits in found.values():
            hits.sort(key=lambda pair: (pair[0].spec.strictness, pair[0].id))
            view, hit = hits[0]
            page = hit.page
            before, matched, after, cut_before, cut_after = self._snippet(
                page.text, hit.start, hit.end, chars
            )
            modifiers = tuple(dict.fromkeys(m for _, h in hits for m in h.modifiers))
            scores = [h.score for _, h in hits if h.score is not None]
            owners = files.get(page.document_id, [])
            for file_id, path in owners:
                original = owners[0][1]
                matches.append(
                    _Match(
                        file_id=file_id,
                        document_id=page.document_id,
                        file_name=Path(path).name,
                        file_path=path,
                        page_number=page.page_number,
                        total_pages=page.total_pages,
                        before=before,
                        matched=matched,
                        after=after,
                        truncated_before=cut_before,
                        truncated_after=cut_after,
                        duplicate_of_path=None if path == original else original,
                        source=page.source,
                        score=max(scores) if scores else None,
                        start=hit.start,
                        end=hit.end,
                        engine=view.id,
                        matched_by=tuple(v.id for v, _ in hits),
                        modifiers=modifiers,
                    )
                )
        return matches

    @staticmethod
    def _snippet(text_: str, start: int, end: int, chars: int) -> tuple[str, str, str, bool, bool]:
        """The text before, of and after a match, with `chars` of context either side."""
        begin = max(0, start - chars)
        stop = min(len(text_), end + chars)
        return text_[begin:start], text_[start:end], text_[end:stop], begin > 0, stop < len(text_)
