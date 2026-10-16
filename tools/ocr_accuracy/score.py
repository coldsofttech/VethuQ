"""Scoring an OCR result against the text a page was rendered from.

CER (character error rate) is the edit distance between the two texts with all whitespace removed,
divided by the length of the reference: 0 is a perfect read, 1 is as wrong as an empty page. Word
recall is the share of the reference's words (counted with repeats, compared exactly after
casefolding and Unicode normalisation) that the OCR text contains.
"""

from __future__ import annotations

import unicodedata
from collections import Counter

try:  # a fast path when it is installed; the pure Python version below gives the same numbers
    from rapidfuzz.distance import Levenshtein as _Fast
except ImportError:  # pragma: no cover - depends on the environment
    _Fast = None


def squeeze(text: str) -> str:
    """The text in Unicode NFC with every whitespace character removed."""
    return "".join(unicodedata.normalize("NFC", text).split())


def distance(a: str, b: str) -> int:
    """The Levenshtein distance between two strings."""
    if _Fast is not None:
        return _Fast.distance(a, b)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def cer(reference: str, text: str) -> float:
    """The character error rate of `text` against `reference`, whitespace ignored."""
    ref, hyp = squeeze(reference), squeeze(text)
    if not ref:
        return 0.0 if not hyp else 1.0
    return distance(ref, hyp) / len(ref)


def words(text: str) -> list[str]:
    return unicodedata.normalize("NFC", text).casefold().split()


def word_recall(reference: str, text: str) -> float:
    """The share of the reference's words that `text` has (1.0 when the reference has none)."""
    wanted = Counter(words(reference))
    total = sum(wanted.values())
    if not total:
        return 1.0
    found = wanted & Counter(words(text))
    return sum(found.values()) / total
