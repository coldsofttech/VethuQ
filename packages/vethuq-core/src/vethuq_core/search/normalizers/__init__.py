"""Normalizers: what counts as "the same character" in a search - see `base.Normalizer`.

Case, Unicode and look-alike folding are applied to the query and the page text alike, whichever
engine decides the shape of the match. They are applied in `Normalizers.ORDER`.
"""

from __future__ import annotations

from vethuq_core.search.normalizers.base import Folded, Normalizer
from vethuq_core.search.normalizers.case import CaseNormalizer
from vethuq_core.search.normalizers.common import NormalizerHelpers, Pipeline
from vethuq_core.search.normalizers.leetspeak import Leet, LeetspeakNormalizer
from vethuq_core.search.normalizers.registry import Normalizers
from vethuq_core.search.normalizers.unicode import UnicodeNormalizer

Normalizers.register(UnicodeNormalizer())
Normalizers.register(CaseNormalizer())
Normalizers.register(LeetspeakNormalizer())

__all__ = [
    "CaseNormalizer",
    "Folded",
    "Leet",
    "LeetspeakNormalizer",
    "Normalizer",
    "NormalizerHelpers",
    "Normalizers",
    "Pipeline",
    "UnicodeNormalizer",
]
