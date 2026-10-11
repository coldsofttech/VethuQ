"""Document readers: open a file and yield its pages, with no OCR involved.

A `DocumentReader` only *extracts*: a page's native text layer and a way to render the page (or
image regions within it) to an image. Deciding whether that needs OCR, and running it, is VethuQ's
job, so a reader can be written and tested without an OCR engine.
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vethuq_addon_api.errors import AddonError

# (x0, y0, x1, y1) in the page's own coordinate space, origin at the top left.
Region = tuple[float, float, float, float]


class UnreadableFileError(AddonError):
    """The file can't be read, and trying again won't change that."""

    def __init__(self, path: Path | str, reason: str = "") -> None:
        self.path = Path(path)
        detail = f" ({reason})" if reason else ""
        super().__init__(f"Can't read {self.path}{detail}.")


class FileRemovedError(UnreadableFileError):
    """The file is gone."""

    def __init__(self, path: Path | str) -> None:
        super().__init__(path, "it no longer exists")


class PasswordProtectedError(UnreadableFileError):
    """The file needs a password."""

    def __init__(self, path: Path | str) -> None:
        super().__init__(path, "it is password-protected")


class CorruptedFileError(UnreadableFileError):
    """The file is damaged."""

    def __init__(self, path: Path | str, reason: str = "") -> None:
        super().__init__(path, f"it is damaged: {reason}" if reason else "it is damaged")


def extended_path(path: Path | str) -> Path:
    """On Windows, the `\\\\?\\` form that lets very long paths be opened; unchanged elsewhere."""
    path = Path(path)
    prefix = "\\\\?\\"
    if sys.platform != "win32" or str(path).startswith(prefix):
        return path
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\"):
        return Path(prefix + "UNC\\" + absolute[2:])
    return Path(prefix + absolute)


@dataclass(frozen=True)
class ReadPage:
    """One page as extracted by a `DocumentReader`.

    `native_text` is the file's own text layer for the page ('' when it has none). `image_regions`
    are the embedded image areas large enough to matter. `render(region)` produces an image of
    the whole page, or just `region`, on demand: rendering is the expensive part, so it only
    happens for pages that need OCR. It returns what an OCR engine accepts, an image file path or
    a BGR pixel array. `width_pt` / `height_pt` are the page size. A `ReadPage` is only valid until
    the iterator that produced it moves on.
    """

    native_text: str
    image_regions: tuple[Region, ...]
    render: Callable[[Region | None], Any]
    # The page's size in points (1/72 inch), as it is displayed (after rotation); None if the
    # reader doesn't know. VethuQ prices a page by its size.
    width_pt: float | None = None
    height_pt: float | None = None


class DocumentReader(ABC):
    """Reads one file type into its pages. Implement this to support a new file type.

    `processing_weight` says how much heavier a file of this type is to process than a single
    image (it sizes the number of worker threads).
    """

    processing_weight: float = 1.0

    @abstractmethod
    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        """Yield the file's pages in order, or only the 1-based `page_number` if given.

        Raise `FileRemovedError`, `PasswordProtectedError` or `CorruptedFileError` (all
        `UnreadableFileError`s) for a file that can't be read.
        """


@dataclass(frozen=True)
class FileTypeSpec:
    """A kind of file an add-on lets VethuQ read.

    `extensions` are lower-case with the dot (`".pdf"`). A type that exists but can't be used
    right now is returned with `available=False` and a `reason`.
    """

    id: str
    label: str
    extensions: tuple[str, ...]
    reader: DocumentReader
    available: bool = True
    reason: str = ""
