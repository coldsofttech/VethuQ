"""Running a search: choosing the engines and their levels, bringing the index up to date, asking
each engine for its hits on the candidate pages, and turning hits into matches in files."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

from vethuq._db import _Database
from vethuq._errors import _SearchOptionError, _SearchQueryError, _SearchUnavailableError
from vethuq._search.engines import ALL, HYBRID, SEMANTIC, _Engines, _EngineView
from vethuq._search.index import _SearchIndex
from vethuq._search.ranking import PageKey, _Found, _Fusion, _Merger, _Ranker
from vethuq_addon_api import AddonError, PageText, SearchCorpus, SearchRequest

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
    # What `sort="rank"` orders by (see `vethuq._search.ranking`); not part of the public match.
    rank: tuple = field(default=(), repr=False, compare=False)


@dataclass
class _Outcome:
    engine: str
    matches: list[_Match]
    levels: dict[str, dict[str, str]]
    index_rebuilt: bool
    pending: dict[str, int] = field(default_factory=dict)  # pages an engine hasn't prepared yet


@dataclass
class _Synced:
    """What preparing one engine's pages did."""

    engine: str
    pages: int = 0
    pending: int = 0
    charged_milli: int = 0
    paused: bool = False
    message: str = ""


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
        options: Mapping[str, Mapping[str, str]] | None = None,
        combine: str | None = None,
        defaults: Mapping[str, Mapping[str, str]] | None = None,
    ) -> _Outcome:
        chosen = self.engines.choose(engine, combine)
        self.engines.check_explicit(explicit)
        options = options or {}
        self.engines.check_options(options, chosen)
        hybrid = engine == HYBRID
        strict = engine not in (ALL, HYBRID)
        if not strict:
            used = {use.id for view in chosen for use in self.engines.uses(view)}
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
        found: dict[PageKey, list[_Found]] = {}
        for view in chosen:
            values = {**self.engines.saved_options(view, defaults), **options.get(view.id, {})}
            request = SearchRequest(query, self.engines.pipeline(levels[view.id]), values)
            # One engine named, or the semantic half of `hybrid`: its failure is the search's.
            must = strict or (hybrid and view.id == SEMANTIC)
            try:
                for hit in view.spec.engine.search(request, corpus):  # type: ignore[union-attr]
                    page = (hit.page.document_id, hit.page.page_number)
                    found.setdefault(page, []).append(_Found(view, hit))
            except AddonError as exc:
                if must:
                    raise _SearchQueryError(str(exc)) from exc
                _logger.info("The %s engine can't search this query: %s", view.id, exc)
            except Exception:  # noqa: BLE001 - one broken engine never spoils an `all` search
                if must:
                    raise
                _logger.warning("The %s engine failed", view.id, exc_info=True)
        matches = self._matches(found, context_chars, hybrid)
        return _Outcome(engine, matches, levels, rebuilt, self._pending(chosen, corpus))

    @staticmethod
    def _pending(chosen: list[_EngineView], corpus: SearchCorpus) -> dict[str, int]:
        """The engines that have pages they haven't prepared, and how many."""
        pending: dict[str, int] = {}
        for view in chosen:
            try:
                count = view.spec.engine.pending(corpus)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - a broken engine never spoils a search
                _logger.warning("The %s engine failed to count its pending pages", view.id)
                continue
            if count > 0:
                pending[view.id] = count
        return pending

    # ----- preparing --------------------------------------------------------------------------

    def sync(
        self, engine: str | None, progress: Callable[[str, int, int], None] | None = None
    ) -> list[_Synced]:
        """Prepare the pages of `engine` (an id; left out, every engine that has something to
        prepare). The search index is brought up to date first. Raises `SearchUnavailableError` for
        a named engine that can't be used or fails."""
        views = self.engines.views()
        if engine is None or engine == ALL:
            targets = [v for v in views if v.available]
            strict = False
        else:
            if engine == HYBRID:
                targets = self.engines.choose(HYBRID)
            else:
                targets = self.engines.choose(engine)
            strict = True
        self.index.sync()
        corpus = _Corpus(self.index, None, self.index.has_fts())
        done: list[_Synced] = []
        for view in targets:

            def report(step: int, total: int, name: str = view.id) -> None:
                if progress is not None:
                    progress(name, step, total)

            try:
                result = view.spec.engine.sync(corpus, report)  # type: ignore[union-attr]
            except AddonError as exc:
                if strict:
                    raise _SearchUnavailableError(str(exc)) from exc
                _logger.info("The %s engine can't be prepared: %s", view.id, exc)
                done.append(_Synced(view.id, message=str(exc)))
                continue
            except Exception:  # noqa: BLE001 - one broken engine never spoils the others
                if strict:
                    raise
                _logger.warning("The %s engine failed to prepare", view.id, exc_info=True)
                continue
            done.append(
                _Synced(
                    view.id,
                    result.pages,
                    result.pending,
                    result.charged_milli,
                    result.paused,
                    result.message,
                )
            )
        return done

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
        self, found: dict[PageKey, list[_Found]], chars: int, hybrid: bool
    ) -> list[_Match]:
        files = self._files({key[0] for key in found})
        # Hits of different engines that overlap are one match, except in `hybrid`, where each
        # engine's hits stand on their own (a passage and the words inside it are both shown).
        clusters = {
            key: (
                [[f] for f in sorted(hits, key=lambda f: (f.hit.start, f.view.id))]
                if hybrid
                else _Merger.clusters(hits)
            )
            for key, hits in found.items()
        }
        fused = self._fused(found) if hybrid else {}
        matches: list[_Match] = []
        for key, page_clusters in clusters.items():
            if hybrid:
                page_rank: tuple = (-fused[key],)
            else:
                page_rank = _Ranker.page_key(page_clusters)
            engines_on_page = tuple(
                dict.fromkeys(
                    f.view.id
                    for f in sorted(
                        (f for c in page_clusters for f in c),
                        key=lambda f: (f.view.spec.strictness, f.view.id),
                    )
                )
            )
            for cluster in page_clusters:
                head = cluster[0]
                hit, page = head.hit, head.hit.page
                before, matched, after, cut_before, cut_after = self._snippet(
                    page.text, hit.start, hit.end, chars
                )
                members = sorted(cluster, key=lambda f: (f.view.spec.strictness, f.view.id))
                modifiers = tuple(dict.fromkeys(m for f in cluster for m in f.hit.modifiers))
                scores = [f.hit.score for f in cluster if f.hit.score is not None]
                matched_by = (
                    engines_on_page if hybrid else tuple(dict.fromkeys(f.view.id for f in members))
                )
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
                            engine=head.view.id,
                            matched_by=matched_by,
                            modifiers=modifiers,
                            rank=(*page_rank, path, page.page_number, hit.start),
                        )
                    )
        return matches

    @staticmethod
    def _fused(found: dict[PageKey, list[_Found]]) -> dict[PageKey, float]:
        """The reciprocal-rank-fusion score of each page, from each engine's own ranking."""
        per_engine: dict[str, dict[PageKey, float]] = {}
        for key, hits in found.items():
            by_engine: dict[str, list[_Found]] = {}
            for item in hits:
                by_engine.setdefault(item.view.id, []).append(item)
            for engine, items in by_engine.items():
                scores = [i.hit.score for i in items if i.hit.score is not None]
                per_engine.setdefault(engine, {})[key] = (
                    max(scores) if scores else float(len(items))
                )
        return _Fusion.scores(per_engine)

    @staticmethod
    def _snippet(text_: str, start: int, end: int, chars: int) -> tuple[str, str, str, bool, bool]:
        """The text before, of and after a match, with `chars` of context either side."""
        begin = max(0, start - chars)
        stop = min(len(text_), end + chars)
        return text_[begin:start], text_[start:end], text_[end:stop], begin > 0, stop < len(text_)
