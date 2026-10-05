"""An `Embedder` for tests that needs no model: words that mean the same share a dimension.

Each *concept* below is one dimension; a word of a concept lights it up, any other word lands in
one of a few hashed dimensions. So "refund" and "reimbursement" (and Telugu "వాపసు") point the
same way while unrelated text points elsewhere, which is all the engine tests need from a model.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence

import numpy as np

CONCEPTS: tuple[frozenset[str], ...] = (
    frozenset({"refund", "reimbursement", "repayment", "return", "money-back", "వాపసు"}),
    frozenset({"museum", "gallery", "exhibition", "మ్యూజియం"}),
    frozenset({"invoice", "bill", "receipt", "చలాన్"}),
    frozenset({"cat", "kitten", "feline", "పిల్లి"}),
)
HASHED = 16
WORD = re.compile(r"[\wఀ-౿-]+")


class FakeEmbedder:
    model = "fake-embedder"

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        vector = np.zeros(len(CONCEPTS) + HASHED, dtype=np.float32)
        for word in WORD.findall(text.lower()):
            for index, concept in enumerate(CONCEPTS):
                if word in concept:
                    vector[index] += 1.0
                    break
            else:
                vector[len(CONCEPTS) + zlib.crc32(word.encode()) % HASHED] += 0.25
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def __init__(self) -> None:
        self.passages: list[str] = []
        self.queries: list[str] = []

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        self.passages.extend(texts)
        return np.array([self._vector(t) for t in texts], dtype=np.float32).reshape(
            len(texts), len(CONCEPTS) + HASHED
        )

    def embed_query(self, text: str) -> np.ndarray:
        self.queries.append(text)
        return self._vector(text)
