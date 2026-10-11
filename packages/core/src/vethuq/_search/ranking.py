"""Merging what several engines found into matches, and ranking them.

The engines answer different questions, so their scores can't be compared: BM25 relevance, a word
similarity, a cosine, no score at all. Rather than blend the numbers, pages are ranked by *match
quality*: how strict the strictest engine that found them is (`SearchEngineSpec.strictness`, lower
is stricter), and only ordered by an engine's own signal within a tier. Which engine is which does
not matter here, so an add-on's engine slots in by its strictness alone.

A *normalization* (accents) is not a tier of its own but a modifier of the engine's: a `like` hit
for `cafe` found as "café" is "contains, with accents". A hit that needed one ranks below every hit
that matched as typed, and above the approximate engines (`SearchEngineSpec.approximate`: fuzzy,
noise-fuzzy, semantic), which are guesses anyway.

Because the engines' matches nest (an exact match is also a substring, a word and a similar word),
a good match is usually found by three or four of them. So hits that overlap are merged into one,
labelled with the strictest engine that found it and listing all of them.

`hybrid` ranks differently: the pages two engines (meaning and words) find are fused by *reciprocal
rank fusion*. A page scores the sum, over the engines that found it, of `1 / (K + its position in
that engine's ranking)`. Only the positions count, because the engines' scores can't be compared,
and a page both engines like rises above a page only one of them found.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections.abc import Mapping
from dataclasses import dataclass

from vethuq._search.engines import _EngineView
from vethuq_addon_api import Hit

PageKey = tuple[int, int]  # (document id, page number)


@dataclass(frozen=True)
class _Found:
    """A hit and the engine that found it."""

    view: _EngineView
    hit: Hit


class _Merger:
    @staticmethod
    def clusters(found: list[_Found]) -> list[list[_Found]]:
        """One page's hits grouped into matches. Hits of different engines that overlap are one
        match; the first of a group is the strictest engine's (the match's span and engine), and a
        group never holds two hits of one engine (a single engine's hits are separate matches)."""
        ordered = sorted(
            found,
            key=lambda f: (
                f.view.spec.strictness,
                f.view.id,
                f.hit.start,
                -(f.hit.end - f.hit.start),
            ),
        )
        clusters: list[list[_Found]] = []
        heads: list[tuple[int, int, list[_Found]]] = []  # (start, index, cluster) by start
        for item in ordered:
            start, end = item.hit.start, item.hit.end
            joined = None
            # Heads sit in start order; those that can overlap are near `start`.
            at = max(bisect_left(heads, (start, -1, [])) - 1, 0)
            for head_start, _, cluster in heads[at:]:
                head = cluster[0].hit
                if head_start > end:
                    break
                overlaps = (
                    head.start < end
                    and start < head.end
                    or (head.start, head.end)
                    == (
                        start,
                        end,
                    )
                )
                if overlaps and all(m.view.id != item.view.id for m in cluster):
                    joined = cluster
                    break
            if joined is not None:
                joined.append(item)
            else:
                cluster = [item]
                clusters.append(cluster)
                insort(heads, (start, len(clusters), cluster), key=lambda h: (h[0], h[1]))
        return clusters


class _Ranker:
    PLAIN, MODIFIED, APPROXIMATE = 0, 1, 2

    @staticmethod
    def tier(cluster: list[_Found]) -> tuple[int, int]:
        """(group, strictness) of a match: what kind of engine found it, then how strict."""
        head = cluster[0]
        spec = head.view.spec
        if spec.approximate:
            group = _Ranker.APPROXIMATE
        elif head.hit.modifiers:
            group = _Ranker.MODIFIED
        else:
            group = _Ranker.PLAIN
        return group, spec.strictness

    @staticmethod
    def signal(clusters: list[list[_Found]]) -> float:
        """What orders pages within a tier: the best score an engine gave a hit on the page, or,
        for engines that don't score, how many matches the page holds."""
        scores = [f.hit.score for cluster in clusters for f in cluster if f.hit.score is not None]
        return max(scores) if scores else float(len(clusters))

    @staticmethod
    def page_key(clusters: list[list[_Found]]) -> tuple[int, int, float]:
        """The rank of a page, before the tie-breakers: (group, strictness, -signal)."""
        group, strictness = min(_Ranker.tier(cluster) for cluster in clusters)
        return group, strictness, -_Ranker.signal(clusters)


class _Fusion:
    # The usual constant of reciprocal rank fusion: how quickly a lower position stops counting.
    K = 60

    @staticmethod
    def scores(per_engine: Mapping[str, Mapping[PageKey, float]]) -> dict[PageKey, float]:
        """The fused score of every page. `per_engine` maps an engine to the signal of each page it
        found (higher is better); the engine's ranking is those pages, best first."""
        fused: dict[PageKey, float] = {}
        for pages in per_engine.values():
            ranking = sorted(pages, key=lambda key: (-pages[key], key))
            for position, key in enumerate(ranking, start=1):
                fused[key] = fused.get(key, 0.0) + 1.0 / (_Fusion.K + position)
        return fused
