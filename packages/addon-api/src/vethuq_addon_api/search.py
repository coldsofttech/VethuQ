"""Searching indexed pages: normalizers and search engines.

A *normalizer* decides what counts as "the same character" (case, accents, ...); a *search
engine* decides the shape of a match (a substring, a whole word, ...). They are separate on
purpose: the engine asks VethuQ for a `Pipeline` of the normalizers that apply to this search and
applies it to the query and to every page's text alike.

VethuQ keeps an index of each page's text in the coarsest form every installed normalizer allows
(`Normalizer.index_form`), and uses it to hand an engine only the pages that can match
(`SearchCorpus.candidates`). The engine has the final say on its own matches. Raise
`SearchQueryError` for a query the engine can't search.

An engine that needs to prepare pages before it can search them (semantic search embeds them)
overrides `SearchEngine.pending` and `SearchEngine.sync`: searching never prepares anything, so it
is always free and fast, and a page that isn't ready yet is simply not found by that engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from vethuq_addon_api.errors import AddonError


class SearchQueryError(AddonError):
    """The query can't be searched by this engine."""


@dataclass(frozen=True)
class Folded:
    """Normalized text, and where each of its characters came from.

    `starts[i]` and `ends[i]` are the span of the original text that folded character `i`
    stands for. Both are None when the fold changed no positions (the usual case), so a span of
    the folded text is the same span of the original.
    """

    text: str
    starts: Sequence[int] | None = None
    ends: Sequence[int] | None = None

    def original(self, start: int, end: int) -> tuple[int, int]:
        """The span of the original text that `text[start:end]` stands for."""
        if self.starts is None or self.ends is None:
            return start, end
        if end <= start:
            position = (
                self.starts[start]
                if start < len(self.starts)
                else (self.ends[-1] if self.ends else 0)
            )
            return position, position
        return self.starts[start], self.ends[end - 1]

    @staticmethod
    def compose(first: Folded, second: Folded) -> Folded:
        """`second` - a fold of `first.text` - as a fold of the text `first` was made from."""
        if first.starts is None or first.ends is None:
            return second
        if second.starts is None or second.ends is None:
            return Folded(second.text, first.starts, first.ends)
        starts = [first.starts[position] for position in second.starts]
        ends = [first.ends[position - 1] for position in second.ends]
        return Folded(second.text, starts, ends)


class Normalizer(ABC):
    """Treats some differences between texts as no difference. Implement this to add one.

    `id` is its short name (`case`); `levels` the values it can be applied at, `identity` among
    them (the level that changes nothing). `order` says when it runs among the others (lower
    first): Unicode before case, so case sees settled characters. Change `version` whenever its
    behaviour changes, so VethuQ rebuilds the search index.
    """

    id: str
    levels: tuple[str, ...]
    identity: str
    order: int = 100
    version: str = "1"

    @abstractmethod
    def fold(self, text: str, level: str) -> Folded:
        """`text` normalized at `level`, with where its characters came from."""

    @abstractmethod
    def index_form(self, text: str) -> str:
        """`text` folded as coarsely as any level does: the form the search index records. Texts
        that any level treats as the same must have the same index form here."""


class Pipeline:
    """Normalizers applied one after another, in the order given, at the levels given."""

    def __init__(self, steps: Sequence[tuple[Normalizer, str]] = ()) -> None:
        for normalizer, level in steps:
            if level not in normalizer.levels:
                raise ValueError(
                    f"{normalizer.id} must be one of {', '.join(normalizer.levels)}, not {level!r}"
                )
        self._steps = list(steps)

    @property
    def levels(self) -> dict[str, str]:
        return {normalizer.id: level for normalizer, level in self._steps}

    @property
    def is_identity(self) -> bool:
        return all(level == normalizer.identity for normalizer, level in self._steps)

    def fold(self, text: str) -> Folded:
        """`text` through every step, with where each character of the result came from."""
        folded = Folded(text)
        for normalizer, level in self._steps:
            if level == normalizer.identity:
                continue
            step = normalizer.fold(folded.text, level)
            if step.text is folded.text and step.starts is None:
                continue
            folded = Folded.compose(folded, step)
        return folded

    @staticmethod
    def index_form(normalizers: Sequence[Normalizer], text: str) -> str:
        """`text` through every normalizer's `index_form`, in `order`."""
        for normalizer in sorted(normalizers, key=lambda n: (n.order, n.id)):
            text = normalizer.index_form(text)
        return text


@dataclass(frozen=True)
class PageText:
    """One page of an indexed document, as a search engine sees it.

    `text` has its line breaks turned into spaces, so a span of it is a span of the text a result
    shows. `source` is how the text was obtained: `native`, `ocr` or `mixed`.
    """

    page_id: int
    document_id: int
    page_number: int
    total_pages: int
    text: str
    source: str = "ocr"


class SearchCorpus(ABC):
    """The pages an engine searches."""

    @abstractmethod
    def candidates(self, query: str | None = None) -> Iterator[PageText]:
        """The pages that can match `query` at any normalization level (a superset: the engine
        still checks). With None, or a query too short to narrow, every page."""


@dataclass(frozen=True)
class SearchRequest:
    """What an engine is asked to search for.

    `options` are the engine's own settings for this search (`threshold`, `distance`, ...), only
    the ones the search set explicitly; anything missing is the engine's to default, from its
    add-on settings or the `SearchOption.default` it declared.
    """

    query: str
    pipeline: Pipeline
    options: Mapping[str, str] = field(default_factory=dict)

    @property
    def levels(self) -> dict[str, str]:
        return self.pipeline.levels


@dataclass(frozen=True)
class Hit:
    """One occurrence of the query: `page.text[start:end]`. `score` is for engines that rank
    (higher is better); `modifiers` names the normalizations the match needed (`accents`)."""

    page: PageText
    start: int
    end: int
    score: float | None = None
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncReport:
    """What `SearchEngine.sync` did. `pending` is what is still not ready; `paused` says it stopped
    because credits ran out (it carries on when they are back); `charged_milli` is what it spent."""

    pages: int = 0
    pending: int = 0
    charged_milli: int = 0
    paused: bool = False
    message: str = ""


class SearchEngine(ABC):
    """Finds the query on pages. Implement this and return it in a `SearchEngineSpec`."""

    @abstractmethod
    def search(self, request: SearchRequest, corpus: SearchCorpus) -> Iterator[Hit]:
        """Every occurrence of `request.query`, applying `request.pipeline` to the query and to
        the page text alike. May raise `SearchQueryError`."""

    def pending(self, corpus: SearchCorpus) -> int:
        """How many pages this engine can't search yet because they aren't prepared (0 for an
        engine that works on the text as it is). Cheap: it is asked for after every search."""
        return 0

    def sync(
        self, corpus: SearchCorpus, progress: Callable[[int, int], None] | None = None
    ) -> SyncReport:
        """Prepare the pages that aren't ready, calling `progress(done, total)` as it goes. Work
        done stays done if it is stopped. The default prepares nothing."""
        return SyncReport()


@dataclass(frozen=True)
class NormalizerUse:
    """How an engine uses a normalizer.

    `default` is the level it runs at unless told otherwise. `fixed` means it cannot run at any
    other level (asking for another one is an error). `stored` says whether the user's saved
    setting for that normalizer reaches this engine; when false only an explicit request does.
    `optional` means the engine works without that normalizer installed (it just can't be asked
    to use it); otherwise the engine is unavailable until the normalizer is installed.
    """

    id: str
    default: str
    fixed: bool = False
    stored: bool = True
    optional: bool = False


@dataclass(frozen=True)
class SearchOption:
    """A setting of one engine that a search can override (`threshold` of `fuzzy`). A search that
    names an option the engine doesn't declare, or a value outside `choices`, is refused before
    the engine runs."""

    name: str
    description: str = ""
    default: str = ""
    choices: Sequence[str] = ()


@dataclass(frozen=True)
class SearchEngineSpec:
    """A search engine an add-on provides. An engine that exists but can't be used right now is
    returned with `available=False` and a `reason`, rather than left out."""

    id: str
    label: str
    engine: SearchEngine | None
    normalizers: Sequence[NormalizerUse] = field(default_factory=tuple)
    options: Sequence[SearchOption] = field(default_factory=tuple)
    available: bool = True
    reason: str = ""
    description: str = ""
    # Engines the `all` search leaves out (for example one that needs a model).
    in_all: bool = True
    strictness: int = 100  # lower is stricter; `all` lists a hit's engines strictest first
    # The engine guesses (typos, meaning) rather than matching the text: `rank` puts what it finds
    # below what the text-matching engines find.
    approximate: bool = False
    # A word or two that names how this engine found a hit ("Exact", "Similar"), shown beside it in
    # exports. Left empty, the label is used.
    badge: str = ""


NormalizerLevels = Mapping[str, str]
