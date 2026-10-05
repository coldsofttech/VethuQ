"""Splitting a page's text into the chunks that get an embedding each.

A page is too long for one vector to describe it well (and for the model to read at all), so
each page is cut into passages of a few sentences. A chunk is a span of the text it was cut
from, so a search hit can point at, and show, exactly the passage that matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """`text[start:end]` of the text it was cut from."""

    start: int
    end: int
    text: str


class Chunker:
    # About 300 characters is a few sentences: enough context for the model to place the
    # passage, short enough that one vector still describes it. Telugu takes more tokens per
    # character than English, so it is kept under what the model reads (512 tokens) too.
    MAX_CHARS = 400
    # A chunk with fewer letters or digits than this (a page number, a rule of dashes) says
    # nothing worth finding.
    MIN_WORD_CHARS = 3

    # A sentence ends at `.`, `!`, `?`, the Devanagari/Telugu danda `।` and a blank line;
    # the ending belongs to the sentence it closes.
    _SENTENCE = re.compile(r"[^.!?।\n]*(?:[.!?।]+|\n+|$)")

    @staticmethod
    def split(text: str, max_chars: int | None = None) -> list[Chunk]:
        """Cut `text` into chunks of at most `max_chars` (default `MAX_CHARS`) characters.

        Sentences are packed together until the next one would not fit; a sentence longer
        than that is cut at its last space. Chunks keep their place in `text` (newlines are
        ordinary whitespace, so spans stay valid when a caller flattens them to spaces), and
        a chunk with no real content is dropped.
        """
        limit = max_chars or Chunker.MAX_CHARS
        spans: list[tuple[int, int]] = []
        for found in Chunker._SENTENCE.finditer(text):
            start, end = found.span()
            if start == end:
                continue
            spans.extend(Chunker._fit(text, start, end, limit))

        chunks: list[Chunk] = []
        current: tuple[int, int] | None = None
        for start, end in spans:
            if current is None:
                current = (start, end)
            elif end - current[0] <= limit:
                current = (current[0], end)
            else:
                Chunker._add(chunks, text, *current)
                current = (start, end)
        if current is not None:
            Chunker._add(chunks, text, *current)
        return chunks

    @staticmethod
    def _fit(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
        """`text[start:end]` as pieces of at most `limit` characters, cut at spaces."""
        pieces = []
        while end - start > limit:
            cut = text.rfind(" ", start + 1, start + limit + 1)
            if cut <= start:
                cut = start + limit
            pieces.append((start, cut))
            start = cut
        pieces.append((start, end))
        return pieces

    @staticmethod
    def _add(chunks: list[Chunk], text: str, start: int, end: int) -> None:
        """Append `text[start:end]` trimmed of surrounding whitespace, if it has content."""
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        piece = text[start:end]
        if sum(1 for char in piece if char.isalnum()) >= Chunker.MIN_WORD_CHARS:
            chunks.append(Chunk(start, end, piece))
