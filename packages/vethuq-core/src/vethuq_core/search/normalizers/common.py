"""Helpers shared by the normalizers: composing folds and applying them in order."""

from __future__ import annotations

from collections.abc import Sequence

from vethuq_core.search.normalizers.base import Folded, Normalizer


class NormalizerHelpers:
    @staticmethod
    def compose(first: Folded, second: Folded, source: str) -> Folded:
        """`second` - a fold of `first.text` - as a fold of the original `source` text."""
        if first.starts is None or first.ends is None:
            return second
        if second.starts is None or second.ends is None:
            return Folded(second.text, first.starts, first.ends)
        starts = [first.starts[position] for position in second.starts]
        ends = [first.ends[position - 1] for position in second.ends]
        return Folded(second.text, starts, ends)


class Pipeline:
    """Normalizers applied one after another - in the order given - to a text."""

    def __init__(self, steps: Sequence[tuple[Normalizer, str]]) -> None:
        self._steps = [(normalizer, level) for normalizer, level in steps]

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
            folded = NormalizerHelpers.compose(folded, step, text)
        return folded
