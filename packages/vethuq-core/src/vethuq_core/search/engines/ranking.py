"""Search every engine at once and rank the pages together (`search --engine all`).

The engines answer different questions, so their scores can't be compared: BM25
relevance, a word similarity, no score at all. Rather than blend the numbers,
pages are ranked by *match quality* - how strict the strictest engine that found
them is - and only ordered by an engine's own signal within a tier:

    Exact > Contains > Relevant > Near > Word > Lookalike > Similar

(`exact` > `like` > `lexical` > `proximity` > `full-text` > `leetspeak` > `fuzzy`.)
`proximity` outranks `full-text` because every page it finds, `full-text` finds too: both
need all the terms, so ranking them the other way round would leave "the words are close
together" with no way to raise a page. `leetspeak` sits between `full-text` and `fuzzy`:
it only swaps known look-alike characters (`3` for `e`) in the very words typed, which is
more certain than `fuzzy`'s guess that a word with a few edits is the one meant, but it
doesn't tolerate the other word forms and word orders `full-text` does.

Because the engines' matches nest (an exact match is also a substring, a word and
a similar word), a good match is usually found by three or four of them. So a page
is one result, and hits that overlap are merged into one, labelled with the
strictest engine that found it and listing all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from vethuq_core.search.engines.base import SearchMatch, SearchQueryError
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.engines.registry import SearchEngines
from vethuq_core.storage import Storage


@dataclass(frozen=True)
class PageResult:
    """A page found by one or more engines, with its hits best first.

    `engine` is the strictest engine that found anything on the page - the page's
    tier - and `matched_by` every engine that did, strictest first. `hits` are
    ordered by their engine's strictness, then by position in the page; each hit
    carries its own `engine` and `matched_by`. `score` is what the page was ordered
    by within its tier: the number of hits (`exact`, `like`), its BM25 relevance
    (`lexical`, `proximity`, `full-text`), its best word similarity (`fuzzy`) or the share of the
    query it matched as typed (`leetspeak`).
    """

    file_id: int
    file_name: str
    file_path: str
    page_number: int | None
    total_pages: int | None
    duplicate_of_path: str | None
    source: str
    engine: str
    matched_by: tuple[str, ...]
    score: float
    hits: tuple[SearchMatch, ...]


class Ranking:
    # Strictest first: the order pages are ranked in, and `matched_by` is listed in.
    TIERS = ("exact", "like", "lexical", "proximity", "full-text", "leetspeak", "fuzzy")

    # What each engine is called to users, in the CLI and the UI alike.
    BADGES = {
        "exact": "Exact",
        "like": "Contains",
        "lexical": "Relevant",
        "proximity": "Near",
        "full-text": "Word",
        "leetspeak": "Lookalike",
        "fuzzy": "Similar",
    }

    # What each badge means in plain language, shared by the CLI and the UI.
    MEANINGS = {
        "exact": "your text exactly as typed - same case, as a whole word",
        "like": "your text anywhere, even inside a longer word, ignoring case",
        "lexical": "your text anywhere, even inside a longer word, best-matching pages first",
        "proximity": "all your words (two or more) close together, within the distance setting",
        "full-text": "all your words as whole words, any case and word form (e.g. plurals)",
        "leetspeak": "your words written with look-alike characters (h3ll0 for hello, p@55w0rd "
        "for password)",
        "fuzzy": "a word close to yours, tolerating typos and OCR misreads (the % is how close)",
    }

    @staticmethod
    def engine_rank(engine: str) -> int:
        """Position of `engine` in `Ranking.TIERS` (0 is strictest)."""
        return Ranking.TIERS.index(engine)

    @staticmethod
    def engine_badge(engine: str, score: float | None = None) -> str:
        """The user-facing name of `engine`; `Similar` also shows how similar the word was."""
        badge = Ranking.BADGES[engine]
        if engine == "fuzzy" and score is not None:
            badge += f" {score:.0%}"
        return badge

    @staticmethod
    def hit_badge(hit: SearchMatch) -> str:
        """The badge of a hit: the strictest engine that found it."""
        return Ranking.engine_badge(
            hit.engine or "like", hit.score if hit.engine == "fuzzy" else None
        )

    @staticmethod
    def _stitch(hits: list[SearchMatch]) -> tuple[int, str]:
        """The page text covered by `hits`' snippets (`before` + `matched` + `after`), and where
        it starts. Overlapping hits' snippets overlap, so together they cover a continuous
        stretch."""
        windows = sorted(
            (hit.start - len(hit.before), hit.before + hit.matched + hit.after)
            for hit in hits
            if hit.start is not None
        )
        base, text = windows[0]
        for start, window in windows[1:]:
            offset = len(text) - (start - base)
            if offset < 0:  # a gap; can't happen for overlapping hits, but never lose text
                text += " " * -offset
                offset = 0
            text += window[offset:]
        return base, text

    @staticmethod
    def _merge(members: list[SearchMatch], chars: int) -> SearchMatch:
        """One hit for overlapping `members`: their union, labelled by the strictest engine."""
        if len(members) == 1:
            only = members[0]
            return replace(only, matched_by=(only.engine,) if only.engine else ())
        best = min(members, key=lambda hit: Ranking.engine_rank(hit.engine or "like"))
        start = min(hit.start for hit in members if hit.start is not None)
        end = max(hit.end for hit in members if hit.end is not None)
        base, text = Ranking._stitch(members)
        first = min(members, key=lambda hit: hit.start if hit.start is not None else 0)
        last = max(members, key=lambda hit: hit.end if hit.end is not None else 0)
        engines = sorted({hit.engine for hit in members if hit.engine}, key=Ranking.engine_rank)
        return replace(
            best,
            before=text[max(0, start - chars - base) : start - base],
            matched=text[start - base : end - base],
            after=text[end - base : end - base + chars],
            truncated_before=first.truncated_before,
            truncated_after=last.truncated_after,
            start=start,
            end=end,
            matched_by=tuple(engines),
        )

    @staticmethod
    def _merge_overlapping(hits: list[SearchMatch], chars: int) -> list[SearchMatch]:
        """Merge the hits of one page whose spans overlap; the rest stay as they are."""
        ordered = sorted(hits, key=lambda hit: (hit.start or 0, -(hit.end or 0)))
        groups: list[list[SearchMatch]] = []
        group_end = -1
        for hit in ordered:
            if groups and (hit.start or 0) < group_end:
                groups[-1].append(hit)
                group_end = max(group_end, hit.end or 0)
            else:
                groups.append([hit])
                group_end = hit.end or 0
        merged = [Ranking._merge(group, chars) for group in groups]
        merged.sort(key=lambda hit: (Ranking.engine_rank(hit.engine or "like"), hit.start or 0))
        return merged

    @staticmethod
    def _tier_score(engine: str, raw: list[SearchMatch]) -> float:
        """What orders pages within `engine`'s tier, from the raw hits it found on the page."""
        if engine in ("exact", "like"):
            return float(len(raw))
        return max((hit.score or 0.0) for hit in raw)

    @staticmethod
    def _run(
        storage: Storage,
        engine: str,
        query: str,
        chars: int,
        case_sensitive: bool,
        threshold: float | None,
        distance: int | None,
    ) -> list[SearchMatch]:
        """Run one engine, giving it only the options it accepts."""
        search = SearchEngines.get(storage, engine).search
        if engine in ("like", "lexical", "leetspeak"):
            return search(query, context_chars=chars, case_sensitive=case_sensitive)
        if engine == "fuzzy":
            return search(
                query, context_chars=chars, case_sensitive=case_sensitive, threshold=threshold
            )
        if engine == "proximity":
            return search(query, context_chars=chars, distance=distance)
        return search(query, context_chars=chars)

    @staticmethod
    def search_all(
        storage: Storage,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
    ) -> list[PageResult]:
        """Search with every engine and return the pages found, best first.

        Each engine applies the options it can: `case_sensitive` reaches `like`, `lexical`,
        `leetspeak` and `fuzzy` (`exact` always matches case, `full-text` and `proximity` never do),
        `threshold` only `fuzzy` and `distance` only `proximity`, each defaulting to the
        user's setting. An engine that can't search the query (`proximity` needs two
        terms, `lexical` three characters) is skipped rather than failing the search.
        """
        chars = SearchEngineHelpers.resolve_context_chars(storage, context_chars)
        runs: dict[str, list[SearchMatch]] = {}
        for engine in Ranking.TIERS:
            try:
                runs[engine] = Ranking._run(
                    storage, engine, query, chars, case_sensitive, threshold, distance
                )
            except SearchQueryError:
                runs[engine] = []

        pages: dict[tuple[int, int | None], dict[str, list[SearchMatch]]] = {}
        for engine, hits in runs.items():
            for hit in hits:
                by_engine = pages.setdefault((hit.file_id, hit.page_number), {})
                by_engine.setdefault(engine, []).append(hit)

        results = []
        for by_engine in pages.values():
            raw = [hit for hits in by_engine.values() for hit in hits]
            hits = Ranking._merge_overlapping(raw, chars)
            best = min(by_engine, key=Ranking.engine_rank)
            first = by_engine[best][0]
            results.append(
                PageResult(
                    file_id=first.file_id,
                    file_name=first.file_name,
                    file_path=first.file_path,
                    page_number=first.page_number,
                    total_pages=first.total_pages,
                    duplicate_of_path=first.duplicate_of_path,
                    source=first.source,
                    engine=best,
                    matched_by=tuple(sorted(by_engine, key=Ranking.engine_rank)),
                    score=Ranking._tier_score(best, by_engine[best]),
                    hits=tuple(hits),
                )
            )

        results.sort(
            key=lambda page: (
                Ranking.engine_rank(page.engine),
                -page.score,
                -len(page.matched_by),
                page.file_path,
                page.page_number or 0,
            )
        )
        return results

    @staticmethod
    def flatten(pages: list[PageResult]) -> list[SearchMatch]:
        """The hits of `pages` as one list, in ranked page order."""
        return [hit for page in pages for hit in page.hits]
