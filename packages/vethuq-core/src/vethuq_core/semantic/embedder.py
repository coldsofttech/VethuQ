"""Turning text into vectors: the `Embedder` interface and the ONNX implementation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from vethuq_core.semantic.model import SemanticModel, SemanticModelError

if TYPE_CHECKING:
    import numpy as np


class Embedder(Protocol):
    """Reads text into normalized float32 vectors; two texts that mean the same get vectors that
    point the same way, so their dot product (their cosine) is close to 1."""

    @property
    def model(self) -> str:
        """Name the vectors are recorded under; vectors of different models don't compare."""
        ...

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        """One row per text of the page text being indexed."""
        ...

    def embed_query(self, text: str) -> np.ndarray:
        """One vector for a search query."""
        ...


class OnnxEmbedder:
    """`Embedder` running `intfloat/multilingual-e5-small` with ONNX Runtime.

    The tokenizer and the session are loaded together, once, from the downloaded model folder.
    """

    BATCH_SIZE = 16

    def __init__(self, onnx_path: Path) -> None:
        try:
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise SemanticModelError(
                "Semantic search needs onnxruntime and tokenizers. "
                "Install them with: pip install vethuq[search-semantic]"
            ) from exc
        tokenizer = Tokenizer.from_file(
            str(SemanticModel.cache_dir() / SemanticModel.TOKENIZER_FILE)
        )
        tokenizer.enable_truncation(max_length=SemanticModel.MAX_TOKENS)
        tokenizer.enable_padding()
        self._tokenizer = tokenizer
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        self._session = onnxruntime.InferenceSession(
            str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}

    @property
    def model(self) -> str:
        return SemanticModel.MODEL_ID

    @staticmethod
    def pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Average `hidden` (batch, tokens, size) over the real tokens `mask` (batch, tokens)
        marks, then scale each row to unit length."""
        import numpy as np

        weights = mask[:, :, None].astype(np.float32)
        total = (hidden * weights).sum(axis=1)
        counts = np.clip(weights.sum(axis=1), 1e-9, None)
        vectors = (total / counts).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-12, None)

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        import numpy as np

        batches = []
        for first in range(0, len(texts), OnnxEmbedder.BATCH_SIZE):
            encoded = self._tokenizer.encode_batch(list(texts[first : first + self.BATCH_SIZE]))
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feed)[0]
            # An export that already pools (batch, size) just needs scaling to unit length.
            batches.append(
                OnnxEmbedder.pool(hidden[:, None, :], np.ones((len(hidden), 1)))
                if hidden.ndim == 2
                else OnnxEmbedder.pool(hidden, mask)
            )
        if not batches:
            return np.zeros((0, SemanticModel.DIMENSIONS), dtype=np.float32)
        return np.concatenate(batches)

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed([SemanticModel.PASSAGE_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([SemanticModel.QUERY_PREFIX + text])[0]


class Embedders:
    """Where the rest of VethuQ gets its `Embedder`: one per process, built on first use
    (downloading the model if it is not there yet)."""

    _instance: Embedder | None = None
    # Replaceable, so tests (and anything with its own model) can supply an embedder without a
    # download.
    _factory: Callable[[], Embedder] | None = None

    @staticmethod
    def get(on_progress: Callable[[str], None] | None = None) -> Embedder:
        """The embedder, downloading the model first if needed. Raises `SemanticModelError`."""
        if Embedders._instance is None:
            if Embedders._factory is not None:
                Embedders._instance = Embedders._factory()
            else:
                Embedders._instance = OnnxEmbedder(SemanticModel.download(on_progress))
        return Embedders._instance

    @staticmethod
    def use(factory: Callable[[], Embedder] | None) -> None:
        """Use `factory` to build the embedder from now on (None: the real one again)."""
        Embedders._factory = factory
        Embedders._instance = None
