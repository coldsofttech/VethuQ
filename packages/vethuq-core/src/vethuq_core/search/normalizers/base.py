"""The normalizer interface: what a search needs from "a way of treating text as equal".

A normalizer maps text to a form in which texts it considers the same are equal - case
folding, accent folding, look-alike folding - and is applied to the query and to the page
text alike. Engines depend only on this module and `registry`, never on a concrete
normalizer, so adding one means adding a `Normalizer` and registering it, just as for
`vethuq_core.search.engines`. Normalizers and engines are separate on purpose: an engine
decides the *shape* of a match (substring, whole word, ranked, edit distance, ...), a
normalizer what counts as *the same character*.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Folded:
    """Normalized text, and where each of its characters came from.

    `starts[i]` and `ends[i]` are the span of the original text that folded character `i`
    stands for. Both are None when the fold changed no positions (the usual case), so a span
    of the folded text is the same span of the original.
    """

    text: str
    starts: Sequence[int] | None = None
    ends: Sequence[int] | None = None

    def original(self, start: int, end: int) -> tuple[int, int]:
        """The span of the original text that `text[start:end]` stands for."""
        if self.starts is None or self.ends is None:
            return start, end
        if end <= start:
            position = self.starts[start] if start < len(self.starts) else len(self.starts)
            return position, position
        return self.starts[start], self.ends[end - 1]


class Normalizer(Protocol):
    """Treats some differences between texts as no difference. Implement this to add one."""

    @property
    def name(self) -> str:
        """Short name, as in `settings search normalize <name>`."""
        ...

    @property
    def levels(self) -> tuple[str, ...]:
        """The values it can be applied at, `identity` among them."""
        ...

    @property
    def identity(self) -> str:
        """The level at which it changes nothing."""
        ...

    def fold(self, text: str, level: str) -> Folded:
        """`text` normalized at `level`, with where its characters came from."""
        ...

    def char_table(self, level: str) -> dict[int, str] | None:
        """A `str.translate` table doing the same one character at a time, or None if
        `fold` isn't a character-for-character substitution (so engines that align
        character by character have a fast path where there is one)."""
        ...
