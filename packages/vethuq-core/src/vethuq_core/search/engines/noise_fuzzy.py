"""The `noise-fuzzy` search engine: words hidden by stray characters, look-alikes and typos.

Finds `hello` in "h..e llo", in "h @ e # l l o", in "h3ll0", in "helo" and in any mix of
those. It is `fuzzy` and `leetspeak` combined with tolerance for noise, working in the order
the text is cleaned up:

1. **Noise is ignored.** Whitespace and punctuation between characters are skipped, as far as
   the noise setting allows. Letters and digits are never noise.
2. **Look-alikes are folded.** The characters of the chosen leetspeak level that stand for a
   letter (`3` for `e`, `@` for `a`) are read as that letter; single characters only - the
   multi-character spellings (`|\\|`) are for `leetspeak`.
3. **Typos are tolerated.** What is left must be within the fuzzy threshold of the query's
   characters, by the same edit rules as `fuzzy` (insert, delete, substitute or swap two
   neighbours; at most 2).

The query goes through the same steps, so it may itself be written with noise or look-alikes,
and its words are matched as one run of characters (`my password` finds "m y p@55w0rd").

A match starts and ends at word edges, like `fuzzy`'s (`hello` finds "ahello" as a
close word, not "shellout"), and its characters may be spread over several words ("he llo").
Candidate pages come from a trigram index over the page's recorded skeleton
(`Leet.skeleton`), so the engine does not read every page - see `narrowing_expression`.
"""

from __future__ import annotations

from dataclasses import dataclass

from vethuq_core.leet import Leet
from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.search.engines.fuzzy import FuzzySearchEngine
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


@dataclass(frozen=True)
class _Kept:
    """The characters of a text that are not noise, in order, with where each one is."""

    folded: str  # the characters folded to their class (what is compared)
    raw: str  # the characters as written, lower-cased unless case-sensitive
    where: list[int]  # each one's index in the original text


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    score: float


class NoiseFuzzySearchEngine:
    """`SearchEngine` that finds query characters hidden by noise, look-alikes and typos.

    Ranked: pages by their best match, a match scoring 1.0 when the text is the query as
    typed and less with every edit, look-alike substitution and noise character it took
    (`SearchMatch.score`). Honours `case_sensitive` (a case difference is one edit, as in
    `fuzzy`), `threshold` (the fuzzy threshold), `level` (the leetspeak level) and `noise`
    (see `SearchSettings.NOISE_LEVELS`), each defaulting to its setting.
    """

    name = "noise-fuzzy"

    MIN_FUZZY_LENGTH = FuzzySearchEngine.MIN_FUZZY_LENGTH
    MAX_EDITS = FuzzySearchEngine.MAX_EDITS
    _TOLERANCE = 1e-9

    # How much each thing a match took lowers its score (which only orders the results).
    EDIT_PENALTY = 0.15
    LOOKALIKE_PENALTY = 0.03
    NOISE_PENALTY = 0.02
    MIN_SCORE = 0.05

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
    ) -> list[SearchMatch]:
        SearchEngineHelpers.require_no_distance(self.name, distance)
        limit = (
            SearchSettings.get_fuzzy_threshold(self._storage)
            if threshold is None
            else SearchSettings.parse_fuzzy_threshold(threshold)
        )
        leet_level = (
            SearchSettings.get_leetspeak_level(self._storage)
            if level is None
            else SearchSettings.parse_leetspeak_level(level)
        )
        noise_level = (
            SearchSettings.get_noise_level(self._storage)
            if noise is None
            else SearchSettings.parse_noise_level(noise)
        )
        gap_cap, total_cap = SearchSettings.NOISE_LEVELS[noise_level]

        wanted = NoiseFuzzySearchEngine._keep(query, leet_level, case_sensitive)
        if not wanted.folded:
            return []
        edits = NoiseFuzzySearchEngine.allowed_edits(wanted.folded, limit)
        skeleton = Leet.skeleton(query)
        expression = NoiseFuzzySearchEngine.narrowing_expression(skeleton, edits)
        chars = SearchEngineHelpers.resolve_context_chars(self._storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(self._storage)

        ranked: list[tuple[float, str, int, list[SearchMatch]]] = []
        for row in (
            *self._storage.search_noise_candidate_pdf_pages(expression),
            *self._storage.search_noise_candidate_image_pages(expression),
        ):
            stretches = NoiseFuzzySearchEngine.candidate_stretches(
                skeleton, edits, row["noise_text"]
            )
            if stretches is not None and not stretches:
                continue
            text = row["ocr_text"].replace("\n", " ")
            hits = NoiseFuzzySearchEngine._page_hits(
                text,
                wanted,
                edits,
                limit,
                leet_level,
                case_sensitive,
                gap_cap,
                total_cap,
                stretches,
            )
            if not hits:
                continue
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
                    start=hit.start,
                    end=hit.end,
                    chars=chars,
                    engine=self.name,
                    score=hit.score,
                )
                for hit in hits
            ]
            best = max(hit.score for hit in hits)
            ranked.append((best, row["file_path"], page_number or 0, page_matches))

        ranked.sort(key=lambda page: (-page[0], page[1], page[2]))
        return [match for *_, page_matches in ranked for match in page_matches]

    # -- the query and the limits ---------------------------------------------------------

    @staticmethod
    def _keep(text: str, level: str, case_sensitive: bool) -> _Kept:
        """`text` reduced to its non-noise characters, folded at `level`."""
        pattern = Leet.kept()
        kept = "".join(pattern.findall(text))
        raw = kept if case_sensitive else kept.lower()
        if len(raw) != len(kept):  # a character whose lower case is longer than itself
            return NoiseFuzzySearchEngine._keep_slowly(text, level, case_sensitive)
        folded = raw.translate(Leet.folding(level, case_sensitive))
        return _Kept(folded, raw, [match.start() for match in pattern.finditer(text)])

    @staticmethod
    def _keep_slowly(text: str, level: str, case_sensitive: bool) -> _Kept:
        folded: list[str] = []
        raw: list[str] = []
        where: list[int] = []
        for index, char in enumerate(text):
            if Leet.is_noise(char):
                continue
            folded.append(Leet.fold(char, level, case_sensitive))
            raw.append(char if case_sensitive else char.lower()[:1])
            where.append(index)
        return _Kept("".join(folded), "".join(raw), where)

    @staticmethod
    def allowed_edits(folded: str, threshold: float) -> int:
        """The most edits a match of the folded query may have (0 up to 2).

        Like `fuzzy`: a query under `MIN_FUZZY_LENGTH` characters, or one still holding a
        digit (an identifier, an amount, a date) after the look-alikes are folded, must
        match exactly. The figure is the most a match could have before it falls under the
        threshold, so it never turns away a match; `_similar` has the final say.
        """
        if len(folded) < NoiseFuzzySearchEngine.MIN_FUZZY_LENGTH or any(
            char.isdigit() for char in folded
        ):
            return 0
        longest = len(folded) + NoiseFuzzySearchEngine.MAX_EDITS
        return min(
            NoiseFuzzySearchEngine.MAX_EDITS,
            int((1 - threshold) * longest + NoiseFuzzySearchEngine._TOLERANCE),
        )

    @staticmethod
    def narrowing_expression(skeleton: str, edits: int) -> str | None:
        """An FTS5 expression over the skeleton trigram index that every page matching holds.

        Only used to skip pages that can't match; the match itself has the final say. The
        query's skeleton (noise dropped, look-alikes folded as coarsely as any level does)
        must appear in a matching page's skeleton:

        * with no edits allowed, as a substring: `"skeleton"`;
        * with `n` characters and `k` edits, at least one of its `n - 2` trigrams survives
          as long as `n - 2 > 3k` (one edit spoils at most three of them), so any will do.

        Returns None when it can't narrow soundly (a skeleton under three characters, or too
        many edits for its length); every page is then examined. A skeleton holds only
        letters and digits, so nothing here needs escaping beyond the quotes.
        """
        if len(skeleton) < SearchEngineHelpers.TRIGRAM_MIN_CHARS:
            return None
        if edits == 0:
            return '"' + skeleton.replace('"', '""') + '"'
        if len(skeleton) - 2 <= 3 * edits:
            return None
        trigrams = sorted({skeleton[i : i + 3] for i in range(len(skeleton) - 2)})
        return " OR ".join('"' + trigram.replace('"', '""') + '"' for trigram in trigrams)

    @staticmethod
    def candidate_stretches(
        skeleton: str, edits: int, page_skeleton: str
    ) -> list[tuple[int, int]] | None:
        """The stretches of a page's recorded skeleton a match can lie in, or None for the
        whole page.

        The skeleton folds look-alikes as coarsely as any level does and drops all noise, and
        it has one character per kept character, so a match at any level or noise setting
        shows up in it at the same place; this looks for it there, in the stored text, before
        the page is read at all. No stretches means the page can't match.

        With no edits the query's skeleton must appear as it is. Otherwise a match holds
        most of the query's two-character pieces: one edit spoils at most three of them, so
        with `n` characters and `k` edits at least `n - 1 - 3k` survive, close to where the
        match starts. Only the stretches where that many pieces fall together are kept, and
        of those only the ones that really hold the query within `k` edits. A query too short
        for a piece to be certain to survive has its whole skeleton searched. A page whose
        skeleton isn't recorded yet (empty) can't be ruled out: None.
        """
        if not page_skeleton:
            return None
        size = len(skeleton)
        if edits == 0:
            stretches = []
            at = page_skeleton.find(skeleton)
            while at != -1:
                stretches.append((at, at + size))
                at = page_skeleton.find(skeleton, at + 1)
            return NoiseFuzzySearchEngine._merged(stretches)
        return [
            (low, high)
            for low, high in NoiseFuzzySearchEngine._anchored_stretches(
                skeleton, page_skeleton, edits
            )
            if NoiseFuzzySearchEngine._approximately_in(skeleton, page_skeleton[low:high], edits)
        ]

    @staticmethod
    def _merged(stretches: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """`stretches` with those that touch or overlap joined, in order."""
        merged: list[tuple[int, int]] = []
        for start, end in sorted(stretches):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def _anchored_stretches(pattern: str, text: str, edits: int) -> list[tuple[int, int]]:
        """Where in `text` a match of `pattern` within `edits` edits can start, as stretches.

        Each occurrence of one of the pattern's two-character pieces votes for the start it
        implies (where the pattern would begin if nothing were edited); a match starts within
        `edits` of the starts of at least `n - 1 - 3 * edits` different pieces. Returns the
        room a match needs from each such start, or all of `text` when no piece is certain
        to survive.
        """
        size = len(pattern)
        need = size - 1 - 3 * edits
        if need < 1:
            return [(0, len(text))]
        votes: dict[int, int] = {}
        for offset in range(size - 1):
            piece = pattern[offset : offset + 2]
            at = text.find(piece)
            while at != -1:
                start = at - offset
                votes[start] = votes.get(start, 0) | (1 << offset)
                at = text.find(piece, at + 1)
        stretches = []
        for start in votes:
            pieces = 0
            for near in range(start - edits, start + edits + 1):
                pieces |= votes.get(near, 0)
            if pieces.bit_count() >= need:
                stretches.append((max(0, start - edits), min(len(text), start + size + 2 * edits)))
        return NoiseFuzzySearchEngine._merged(stretches)

    @staticmethod
    def _approximately_in(pattern: str, text: str, edits: int) -> bool:
        """Whether `pattern` occurs in `text` within `edits` edits (Sellers' algorithm, with
        the same swaps as the match itself), stopping at the first occurrence."""
        size = len(pattern)
        before = previous = list(range(size + 1))
        for j, char in enumerate(text, start=1):
            cost = [0] * (size + 1)
            for i in range(1, size + 1):
                best = min(
                    previous[i - 1] + (pattern[i - 1] != char),
                    previous[i] + 1,
                    cost[i - 1] + 1,
                )
                if i > 1 and j > 1 and pattern[i - 1] == text[j - 2] and pattern[i - 2] == char:
                    best = min(best, before[i - 2] + 1)
                cost[i] = best
            if cost[size] <= edits:
                return True
            before, previous = previous, cost
        return False

    # -- finding matches on a page ---------------------------------------------------------

    @staticmethod
    def _page_hits(
        text: str,
        wanted: _Kept,
        edits: int,
        threshold: float,
        level: str,
        case_sensitive: bool,
        gap_cap: int,
        total_cap: int,
        stretches: list[tuple[int, int]] | None = None,
    ) -> list[_Hit]:
        """The matches on a page, in text order, none overlapping.

        Only the `stretches` (of the page's kept characters) are searched, or all of it.
        """
        page = NoiseFuzzySearchEngine._keep(text, level, case_sensitive)
        pattern = wanted.folded
        found: list[list[tuple[int, int]]] = []
        for low, high in stretches if stretches is not None else [(0, len(page.folded))]:
            region = page.folded[low:high]
            spans = (
                NoiseFuzzySearchEngine._exact_spans(pattern, region)
                if edits == 0
                else NoiseFuzzySearchEngine._approximate_spans(pattern, region, edits)
            )
            found.extend([(start + low, end + low) for start, end in each] for each in spans)
        hits: list[_Hit] = []
        taken_until = -1
        for candidates in found:
            for start, end in candidates:
                hit = NoiseFuzzySearchEngine._accept(
                    text,
                    page,
                    wanted,
                    start,
                    end,
                    edits,
                    threshold,
                    case_sensitive,
                    gap_cap,
                    total_cap,
                )
                if hit is not None and hit.start >= taken_until:
                    hits.append(hit)
                    taken_until = hit.end
                    break
        return hits

    @staticmethod
    def _exact_spans(pattern: str, folded: str) -> list[list[tuple[int, int]]]:
        """Where `pattern` occurs in `folded`, one candidate per occurrence."""
        spans = []
        position = folded.find(pattern)
        while position != -1:
            spans.append([(position, position + len(pattern))])
            position = folded.find(pattern, position + 1)
        return spans

    @staticmethod
    def _approximate_spans(pattern: str, folded: str, edits: int) -> list[list[tuple[int, int]]]:
        """Where `pattern` occurs in `folded` within `edits` edits (Sellers' algorithm).

        Returns the occurrences found, each as its candidate `(start, end)` spans - the
        cheapest first - for the neighbouring ends of one occurrence. Edits are insertions,
        deletions, substitutions and swaps of two neighbours, as in `fuzzy`.
        """
        size = len(pattern)
        # Column j holds, per pattern prefix i, the fewest edits of a window ending at j and
        # where that window starts (the earliest, on a tie: a window that keeps more of the
        # query beats one that drops a character of it). Two columns back are kept for swaps.
        before_cost: list[int] = []
        before_start: list[int] = []
        previous_cost = list(range(size + 1))
        previous_start = [0] * (size + 1)
        clusters: list[list[tuple[int, int, int]]] = []
        open_cluster: list[tuple[int, int, int]] | None = None
        for j in range(1, len(folded) + 1):
            char = folded[j - 1]
            cost = [0] * (size + 1)
            start = [0] * (size + 1)
            start[0] = j
            for i in range(1, size + 1):
                best_cost = previous_cost[i - 1] + (pattern[i - 1] != char)
                best_start = previous_start[i - 1]
                candidate = previous_cost[i] + 1
                if candidate < best_cost or (
                    candidate == best_cost and previous_start[i] < best_start
                ):
                    best_cost, best_start = candidate, previous_start[i]
                candidate = cost[i - 1] + 1
                if candidate < best_cost or (candidate == best_cost and start[i - 1] < best_start):
                    best_cost, best_start = candidate, start[i - 1]
                if i > 1 and j > 1 and pattern[i - 1] == folded[j - 2] and pattern[i - 2] == char:
                    candidate = before_cost[i - 2] + 1
                    if candidate < best_cost or (
                        candidate == best_cost and before_start[i - 2] < best_start
                    ):
                        best_cost, best_start = candidate, before_start[i - 2]
                cost[i], start[i] = best_cost, best_start
            if cost[size] <= edits:
                if open_cluster is None:
                    open_cluster = []
                    clusters.append(open_cluster)
                open_cluster.append((cost[size], j, start[size]))
            else:
                open_cluster = None
            before_cost, before_start = previous_cost, previous_start
            previous_cost, previous_start = cost, start
        return [[(start, end) for _, end, start in sorted(cluster)] for cluster in clusters]

    @staticmethod
    def _accept(
        text: str,
        page: _Kept,
        wanted: _Kept,
        start: int,
        end: int,
        edits: int,
        threshold: float,
        case_sensitive: bool,
        gap_cap: int,
        total_cap: int,
    ) -> _Hit | None:
        """The match for the characters `page.folded[start:end]`, or None if they don't count.

        The window is widened to the word edges it touches (a match can't start or end inside
        a longer word), then must be within the threshold of the query and hold no more noise
        than allowed.
        """
        where = page.where
        while start > 0 and where[start - 1] + 1 == where[start] and page.raw[start - 1].isalnum():
            start -= 1
        while end < len(where) and where[end - 1] + 1 == where[end] and page.raw[end].isalnum():
            end += 1
        window = page.folded[start:end]
        distance = FuzzySearchEngine.edit_distance(wanted.folded, window, edits)
        if distance > edits:
            return None
        longest = max(len(wanted.folded), len(window))
        if distance and 1 - distance / longest < threshold - NoiseFuzzySearchEngine._TOLERANCE:
            return None
        noise = where[end - 1] + 1 - where[start] - (end - start)
        gap = max((where[t + 1] - where[t] - 1 for t in range(start, end - 1)), default=0)
        if noise > total_cap or gap > gap_cap:
            return None
        lookalikes = NoiseFuzzySearchEngine._lookalikes(
            wanted, window, page.raw[start:end], case_sensitive
        )
        score = max(
            NoiseFuzzySearchEngine.MIN_SCORE,
            1
            - NoiseFuzzySearchEngine.EDIT_PENALTY * distance
            - NoiseFuzzySearchEngine.LOOKALIKE_PENALTY * lookalikes
            - NoiseFuzzySearchEngine.NOISE_PENALTY * noise,
        )
        return _Hit(where[start], where[end - 1] + 1, score)

    @staticmethod
    def _lookalikes(wanted: _Kept, window: str, window_raw: str, case_sensitive: bool) -> int:
        """How many characters matched as a look-alike: equal once folded, but not as written.

        Counted along the cheapest alignment of the query with the window (a position-by-
        position comparison when they are the same length, as they are with no edits).
        """
        pattern = wanted.folded
        if len(pattern) == len(window):
            return sum(
                folded_a == folded_b and raw_a != raw_b
                for folded_a, folded_b, raw_a, raw_b in zip(
                    pattern, window, wanted.raw, window_raw, strict=True
                )
            )
        rows, cols = len(pattern), len(window)
        table = [[0] * (cols + 1) for _ in range(rows + 1)]
        for i in range(rows + 1):
            table[i][0] = i
        for j in range(cols + 1):
            table[0][j] = j
        for i in range(1, rows + 1):
            for j in range(1, cols + 1):
                table[i][j] = min(
                    table[i - 1][j] + 1,
                    table[i][j - 1] + 1,
                    table[i - 1][j - 1] + (pattern[i - 1] != window[j - 1]),
                )
        count = 0
        i, j = rows, cols
        while i > 0 and j > 0:
            if table[i][j] == table[i - 1][j - 1] + (pattern[i - 1] != window[j - 1]):
                if pattern[i - 1] == window[j - 1] and wanted.raw[i - 1] != window_raw[j - 1]:
                    count += 1
                i, j = i - 1, j - 1
            elif table[i][j] == table[i - 1][j] + 1:
                i -= 1
            else:
                j -= 1
        return count
