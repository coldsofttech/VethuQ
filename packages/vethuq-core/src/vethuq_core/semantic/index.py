"""The semantic index: an embedding for every chunk of every searchable page.

Embedding is the slow part of semantic search, so it is done once, ahead of the search, and
only for pages that have no embedding yet - a page whose text changes or is deleted loses its
vectors (see `vethuq_core.db.queries.semantic`) and is picked up again here. `vethuq semantic
index` brings the whole index up to date with progress; a semantic search does the same for
whatever is missing before it looks.

The vectors are kept in a store of their own, beside the main database, and versioned: each
page records the model and the `SemanticIndex.version()` it was embedded with, and vectors of
any other version are dropped and made again, so a change to how text is cut or prepared
never leaves vectors that disagree with a query embedded the new way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vethuq_core.logs import Logs
from vethuq_core.semantic.chunker import Chunker
from vethuq_core.semantic.embedder import Embedder
from vethuq_core.storage import Storage

_logger = Logs.get_logger("index")


@dataclass(frozen=True)
class SemanticIndexStatus:
    """How much of the searchable text is embedded."""

    model: str
    pages: int
    embedded: int
    chunks: int
    # Pages embedded with another version: not searched, and embedded again by the next sync.
    stale: int = 0
    version: str = ""
    # The store's file and its size on disk (0 if it is not there yet).
    path: Path | None = None
    size_bytes: int = 0

    @property
    def pending(self) -> int:
        return self.pages - self.embedded


@dataclass(frozen=True)
class SemanticIndexResult:
    """What one `SemanticIndex.sync` embedded."""

    pages: int
    chunks: int


class SemanticIndex:
    # The version of how a page's text becomes vectors: how it is cut (`Chunker`), what is put
    # in front of it and how the model's output is pooled. Bump it when any of that changes, so
    # vectors made the old way are dropped and made again; `Chunker.MAX_CHARS` is part of the
    # version key, so changing it needs no bump.
    VERSION = 1

    # Pages embedded (and committed) at a time: small enough that an interrupted run keeps most
    # of its work, large enough that the model sees full batches of chunks.
    PAGES_PER_BATCH = 8

    @staticmethod
    def version() -> str:
        """What vectors made now are labelled with: the format version and the chunk size."""
        return f"{SemanticIndex.VERSION}/{Chunker.MAX_CHARS}"

    @staticmethod
    def status(storage: Storage, embedder_model: str) -> SemanticIndexStatus:
        version = SemanticIndex.version()
        counts = storage.count_semantic(embedder_model, version)
        path = storage.semantic_store_path()
        size = 0
        if path is not None:
            size = sum(
                Path(f"{path}{suffix}").stat().st_size
                for suffix in ("", "-wal")
                if Path(f"{path}{suffix}").exists()
            )
        return SemanticIndexStatus(
            model=embedder_model,
            pages=counts["pages"],
            embedded=counts["embedded"],
            chunks=counts["chunks"],
            stale=counts["stale"],
            version=version,
            path=path,
            size_bytes=size,
        )

    @staticmethod
    def sync(
        storage: Storage,
        embedder: Embedder,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> SemanticIndexResult:
        """Embed every searchable page the model has not embedded yet.

        `on_progress(done, total)` fires after each batch of pages. Each batch is committed on
        its own, so stopping early (or a failure) keeps what was done.
        """
        version = SemanticIndex.version()
        with storage.transaction():
            storage.purge_stale_semantic(embedder.model, version)
        total = storage.count_semantic(embedder.model, version)
        todo = total["pages"] - total["embedded"]
        pages_done = chunks_done = 0
        while True:
            rows = storage.list_unembedded_pages(
                embedder.model, version, SemanticIndex.PAGES_PER_BATCH
            )
            if not rows:
                break
            chunks_done += SemanticIndex._embed_pages(storage, embedder, rows)
            pages_done += len(rows)
            if on_progress is not None:
                on_progress(pages_done, max(todo, pages_done))
        if pages_done:
            _logger.info(
                "Semantic index: embedded %d pages (%d chunks) with %s",
                pages_done,
                chunks_done,
                embedder.model,
            )
        return SemanticIndexResult(pages=pages_done, chunks=chunks_done)

    @staticmethod
    def _embed_pages(storage: Storage, embedder: Embedder, rows) -> int:
        """Embed and record `rows` (pages); returns the chunks written."""
        import numpy as np

        per_page = []
        texts: list[str] = []
        for row in rows:
            # Newlines read as spaces, one for one, so a chunk's span is valid in the text
            # the engines show and highlight.
            chunks = Chunker.split(row["ocr_text"].replace("\n", " "))
            per_page.append((row["kind"], row["page_id"], chunks))
            texts.extend(chunk.text for chunk in chunks)
        vectors = embedder.embed_passages(texts) if texts else np.zeros((0, 0), dtype=np.float32)
        written = 0
        with storage.transaction():
            offset = 0
            for kind, page_id, chunks in per_page:
                recorded = [
                    (
                        index,
                        chunk.start,
                        chunk.end,
                        np.ascontiguousarray(vectors[offset + index], dtype=np.float32).tobytes(),
                    )
                    for index, chunk in enumerate(chunks)
                ]
                storage.replace_semantic_page(
                    kind, page_id, embedder.model, SemanticIndex.version(), recorded
                )
                offset += len(chunks)
                written += len(chunks)
        return written

    @staticmethod
    def clear(storage: Storage, embedder_model: str | None = None) -> int:
        """Forget the embeddings (of one model, or all). Returns the pages dropped."""
        with storage.transaction():
            return storage.clear_semantic(embedder_model)
