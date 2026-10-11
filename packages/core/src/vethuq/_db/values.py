"""Values stored in the database that the public API doesn't expose."""

from __future__ import annotations

from enum import StrEnum


class _PageSource(StrEnum):
    """How a page's text was produced."""

    NATIVE = "native"  # straight from the file's text layer, no OCR
    OCR = "ocr"  # read from an image of the page
    MIXED = "mixed"  # the text layer, plus OCR of the images on the page


class _PassStatus(StrEnum):
    """Where a file's read in one language is."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


class _PassSource(StrEnum):
    """How a language came to be read."""

    DEFAULT = "default"  # the system default or the global setting
    AUTO = "auto"  # chosen by detection
    MANUAL = "manual"  # chosen for the source
