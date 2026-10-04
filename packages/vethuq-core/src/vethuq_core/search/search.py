"""Search across previously OCR-indexed content.

`Search.indexed_content` is a thin facade over `vethuq_core.search.engines`: the matching
lives behind the `SearchEngine` interface so implementations can be swapped or chained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from vethuq_core.logs import Logs
from vethuq_core.search.engines import PageResult, Ranking, SearchEngines, SearchMatch
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage

# Searches always follow opening the database, which sets up this log.
_logger = Logs.get_logger("database")


@dataclass(frozen=True)
class FileMatch:
    """One file with at least one matching page - `SearchMatch`es collapsed per file."""

    file_id: int
    file_name: str
    file_path: str
    is_duplicate: bool


class SearchOptionError(ValueError):
    """A search option combination that can't be honoured.

    `option` is which argument to blame: 'engine', 'case_sensitive', 'threshold', 'distance',
    'level', 'noise' or 'unicode'.
    """

    def __init__(self, message: str, option: str) -> None:
        super().__init__(message)
        self.option = option


class SearchOptions(NamedTuple):
    """The resolved options a search runs with.

    `threshold` is set for `fuzzy`, `noise-fuzzy` and `all`, `distance` for `proximity` and
    `all`, `level` (the leetspeak normalization) for `like`, `noise-fuzzy` and `all`, and `noise`
    (the noise level) for `noise-fuzzy` and `all`, and `unicode` (the Unicode normalization)
    for `like`, `exact`, `fuzzy`, `noise-fuzzy` and `all`.
    """

    engine: str
    case_sensitive: bool
    threshold: float | None = None
    distance: int | None = None
    level: str | None = None
    noise: str | None = None
    unicode: str | None = None


class Search:
    @staticmethod
    def resolve_options(
        storage: Storage,
        engine: str | None,
        case_sensitive: bool | None,
        threshold: float | str | None = None,
        distance: int | str | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> SearchOptions:
        """Work out the engine, case sensitivity, fuzzy threshold, proximity distance,
        leetspeak level and noise level.

        Each falls back to its setting when None. The engines differ in what they
        can honour: `exact` is always case-sensitive while `full-text` and
        `proximity` never are, only `fuzzy` and `noise-fuzzy` have a similarity `threshold`,
        only `proximity` has a word `distance`, only `like` and `noise-fuzzy` have a
        `level`, and only `noise-fuzzy` has a `noise` level. `all` runs
        every engine, each applying the options it can, so it accepts them all and never
        rejects one. A
        preference that came from the *setting* is simply not applied where the engine
        can't use it, but one asked for explicitly that the engine can't honour raises
        `SearchOptionError` rather than being silently ignored - as does an
        unknown `engine`, or a `threshold`, `distance`, `level` or `noise` that isn't a valid
        value (see `SearchSettings.parse_fuzzy_threshold`, `parse_proximity_distance`,
        `parse_leetspeak` and `parse_noise_level`).
        """
        if engine is not None and engine not in SearchSettings.ENGINES:
            raise SearchOptionError(
                f"{engine!r} is not one of {', '.join(SearchSettings.ENGINES)}.", "engine"
            )
        resolved_engine = engine if engine is not None else SearchSettings.get_engine(storage)
        if threshold is not None:
            try:
                threshold = SearchSettings.parse_fuzzy_threshold(threshold)
            except ValueError as exc:
                raise SearchOptionError(str(exc), "threshold") from exc
            if resolved_engine not in ("fuzzy", "noise-fuzzy", SearchSettings.ENGINE_ALL):
                raise SearchOptionError(
                    "Only the fuzzy and noise-fuzzy engines have a similarity threshold; "
                    "use --engine fuzzy or noise-fuzzy to set one.",
                    "threshold",
                )
        if distance is not None:
            try:
                distance = SearchSettings.parse_proximity_distance(distance)
            except ValueError as exc:
                raise SearchOptionError(str(exc), "distance") from exc
            if resolved_engine not in ("proximity", SearchSettings.ENGINE_ALL):
                raise SearchOptionError(
                    "Only the proximity engine has a word distance; "
                    "use --engine proximity (or the proximity engine) to set one.",
                    "distance",
                )
        if level is not None:
            try:
                level = SearchSettings.parse_leetspeak(level)
            except ValueError as exc:
                raise SearchOptionError(str(exc), "level") from exc
            if resolved_engine not in ("like", "noise-fuzzy", SearchSettings.ENGINE_ALL):
                raise SearchOptionError(
                    "Only the like and noise-fuzzy engines have a leetspeak level; "
                    "use --engine like or noise-fuzzy to set one.",
                    "level",
                )
        if noise is not None:
            try:
                noise = SearchSettings.parse_noise_level(noise)
            except ValueError as exc:
                raise SearchOptionError(str(exc), "noise") from exc
            if resolved_engine not in ("noise-fuzzy", SearchSettings.ENGINE_ALL):
                raise SearchOptionError(
                    "Only the noise-fuzzy engine has a noise level; "
                    "use --engine noise-fuzzy to set one.",
                    "noise",
                )
        if unicode is not None:
            try:
                unicode = SearchSettings.parse_unicode(unicode)
            except ValueError as exc:
                raise SearchOptionError(str(exc), "unicode") from exc
            if resolved_engine not in ("like", "exact", "fuzzy", "noise-fuzzy", "all"):
                raise SearchOptionError(
                    "Only the like, exact, fuzzy and noise-fuzzy engines have a unicode "
                    "setting; use one of them to set one.",
                    "unicode",
                )
        stored_unicode = (
            unicode
            if unicode is not None
            else SearchSettings.resolve_unicode(storage, SearchSettings.DEFAULT_UNICODE)
        )
        if resolved_engine == SearchSettings.ENGINE_ALL:
            return SearchOptions(
                resolved_engine,
                (
                    case_sensitive
                    if case_sensitive is not None
                    else SearchSettings.is_case_sensitive(storage)
                ),
                threshold if threshold is not None else SearchSettings.get_fuzzy_threshold(storage),
                (
                    distance
                    if distance is not None
                    else SearchSettings.get_proximity_distance(storage)
                ),
                (
                    level
                    if level is not None
                    else SearchSettings.resolve_leetspeak(storage, SearchSettings.DEFAULT_LEETSPEAK)
                ),
                noise if noise is not None else SearchSettings.get_noise_level(storage),
                stored_unicode,
            )
        if resolved_engine in ("full-text", "proximity"):
            if case_sensitive:
                raise SearchOptionError(
                    f"The {resolved_engine} engine is always case-insensitive; "
                    "use the like, exact, fuzzy or noise-fuzzy engine for a case-sensitive search.",
                    "case_sensitive",
                )
            if resolved_engine == "proximity":
                effective_distance = (
                    distance
                    if distance is not None
                    else SearchSettings.get_proximity_distance(storage)
                )
                return SearchOptions(resolved_engine, False, None, effective_distance)
            return SearchOptions(resolved_engine, False)
        if resolved_engine == "exact":
            if case_sensitive is False:
                raise SearchOptionError(
                    "The exact engine is always case-sensitive; "
                    "use the like, full-text, fuzzy, proximity or noise-fuzzy engine "
                    "for a case-insensitive search.",
                    "case_sensitive",
                )
            return SearchOptions(
                resolved_engine, True, None, None, None, None, "off" if unicode is None else unicode
            )
        if case_sensitive is None:
            case_sensitive = SearchSettings.is_case_sensitive(storage)
        if resolved_engine == "fuzzy":
            effective = (
                threshold if threshold is not None else SearchSettings.get_fuzzy_threshold(storage)
            )
            return SearchOptions(
                resolved_engine, case_sensitive, effective, None, None, None, stored_unicode
            )
        if resolved_engine == "like":
            effective_level = (
                level
                if level is not None
                else SearchSettings.resolve_leetspeak(storage, SearchSettings.LEETSPEAK_OFF)
            )
            return SearchOptions(
                resolved_engine,
                case_sensitive,
                None,
                None,
                effective_level,
                None,
                stored_unicode,
            )
        if resolved_engine == "noise-fuzzy":
            return SearchOptions(
                resolved_engine,
                case_sensitive,
                threshold if threshold is not None else SearchSettings.get_fuzzy_threshold(storage),
                None,
                (
                    level
                    if level is not None
                    else SearchSettings.resolve_leetspeak(storage, SearchSettings.DEFAULT_LEETSPEAK)
                ),
                noise if noise is not None else SearchSettings.get_noise_level(storage),
                stored_unicode,
            )
        return SearchOptions(resolved_engine, case_sensitive)

    @staticmethod
    def indexed_pages(
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> list[PageResult]:
        """Search with every engine and return the pages found, best first (see `ranking`).

        Pages are ranked by how strict the strictest engine that found them is - Exact,
        Contains, Relevant, Near, Word, Lookalike, Similar, then Obscured - and within that
        by the engine's own signal.
        Each page lists its hits, best first, each labelled with the engine that found it.
        `case_sensitive` reaches the engines that can honour it, `threshold` (0-1) is the
        fuzzy (and noise-fuzzy) engine's, `distance` the proximity engine's, `level` the
        leetspeak normalization of `like` and `noise-fuzzy` and `noise` the noise-fuzzy engine's,
        each defaulting to the user's setting.
        """
        try:
            return Ranking.search_all(
                storage,
                query,
                context_chars=context_chars,
                case_sensitive=case_sensitive,
                threshold=threshold,
                distance=distance,
                level=level,
                noise=noise,
                unicode=unicode,
            )
        except Exception as exc:
            _logger.error(
                "Search failed: engine=all case_sensitive=%s threshold=%s distance=%s "
                "level=%s noise=%s unicode=%s query_length=%d error=%s: %s",
                case_sensitive,
                threshold,
                distance,
                level,
                noise,
                unicode,
                len(query),
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise

    @staticmethod
    def indexed_content(
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        engine: str | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> list[SearchMatch]:
        """Search indexed OCR text for `query` using the named (default: `like`) engine.

        Returns one `SearchMatch` per occurrence of `query`, ordered by file path
        (pages of the same PDF stay in page order, occurrences within a page in
        text order) - or best match first for the ranked `full-text`, `fuzzy` and
        `proximity` engines. `engine="all"` runs every engine and returns the hits of
        `indexed_pages`, in ranked page order. Only successfully indexed documents
        are considered.
        `like` is case-insensitive unless `case_sensitive`; `exact` is always
        case-sensitive; `full-text` and `proximity` can't be (asking for it raises
        `ValueError`). `fuzzy` finds words within `threshold` similarity (0-1,
        default the user's setting) of the query's, and `proximity` finds passages
        where all the query's terms sit within `distance` words (default the user's
        setting); the other engines raise `ValueError` if given a `threshold` or
        `distance` they don't use. `like` and `noise-fuzzy` read look-alike characters as the
        letters they stand for at the leetspeak `level` (default the user's setting, or the
        engine's own); the other engines raise `ValueError` if given one. `noise-fuzzy` finds
        the query's characters hidden by stray characters (up to the `noise` level),
        look-alikes and typos; the engines that don't use `noise` raise `ValueError` if
        given one.
        `proximity` needs at least two terms (`SearchQueryError` otherwise).
        """
        if engine == SearchSettings.ENGINE_ALL:
            return Ranking.flatten(
                Search.indexed_pages(
                    storage,
                    query,
                    context_chars=context_chars,
                    case_sensitive=case_sensitive,
                    threshold=threshold,
                    distance=distance,
                    level=level,
                    noise=noise,
                    unicode=unicode,
                )
            )
        try:
            return SearchEngines.get(storage, engine).search(
                query,
                context_chars=context_chars,
                case_sensitive=case_sensitive,
                threshold=threshold,
                distance=distance,
                level=level,
                noise=noise,
                unicode=unicode,
            )
        except Exception as exc:
            _logger.error(
                "Search failed: engine=%s case_sensitive=%s threshold=%s distance=%s "
                "level=%s noise=%s unicode=%s query_length=%d error=%s: %s",
                engine or "default",
                case_sensitive,
                threshold,
                distance,
                level,
                noise,
                unicode,
                len(query),
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise

    @staticmethod
    def files(
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        engine: str | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> list[FileMatch]:
        """Search like `indexed_content`, but return one `FileMatch` per matching file.

        Files keep the order of their first matching page (so, by file path, or by
        relevance for the ranked `full-text`, `fuzzy` and `proximity` engines).
        """
        files: dict[int, FileMatch] = {}
        for match in Search.indexed_content(
            storage,
            query,
            context_chars=context_chars,
            engine=engine,
            case_sensitive=case_sensitive,
            threshold=threshold,
            distance=distance,
            level=level,
            noise=noise,
            unicode=unicode,
        ):
            files.setdefault(
                match.file_id,
                FileMatch(
                    file_id=match.file_id,
                    file_name=match.file_name,
                    file_path=match.file_path,
                    is_duplicate=match.duplicate_of_path is not None,
                ),
            )
        return list(files.values())
