"""A model-free `Embedder` for the CLI tests: words of one concept share a dimension."""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence

import numpy as np
from vethuq_core.semantic import SemanticModel

CONCEPTS = (
    frozenset({"refund", "reimbursement", "repayment", "return"}),
    frozenset({"museum", "gallery", "exhibition"}),
)
HASHED = 16


class FakeEmbedder:
    # The real model's name, so the commands that report on it see what this embeds.
    model = SemanticModel.MODEL_ID

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        vector = np.zeros(len(CONCEPTS) + HASHED, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            for index, concept in enumerate(CONCEPTS):
                if word in concept:
                    vector[index] += 1.0
                    break
            else:
                vector[len(CONCEPTS) + zlib.crc32(word.encode()) % HASHED] += 0.25
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        return np.array([self._vector(t) for t in texts], dtype=np.float32).reshape(
            len(texts), len(CONCEPTS) + HASHED
        )

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)
