"""Document readers: open a file and yield its pages, with no OCR involved.

A `DocumentReader` only *extracts* - a page's native text layer and a way to render the
page (or embedded image regions within it) to an image. Deciding whether that
content needs OCR, and running it, is the OCR pipeline's job (`vethuq_core.ocr`),
so reading can be reused and tested without pulling in an OCR engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq_core.fspath import FsPath
from vethuq_core.readers.errors import (
    CorruptedFileError,
    FileRemovedError,
    PasswordProtectedError,
)
from vethuq_core.readers.storage import ImagePageStorage, PageStorage, PdfPageStorage

# numpy/pymupdf/cv2 are imported lazily inside the methods that use them (not
# here at module level) since they're heavy - importing this module shouldn't
# pull them in as a side effect.
if TYPE_CHECKING:
    import numpy as np
    import pymupdf

# (x0, y0, x1, y1) in the page's own coordinate space.
Region = tuple[float, float, float, float]


@dataclass(frozen=True)
class ReadPage:
    """One page as extracted by a `DocumentReader`.

    `native_text` is the file's own text layer for the page ('' when the format
    has none, e.g. an image). `image_regions` are the embedded image areas large
    enough to matter. `render(region)` produces an image of the whole page, or
    just `region`, on demand - rendering is the expensive part, so it only
    happens for pages the caller decides need OCR. A `ReadPage` is only valid
    until the iterator that produced it advances (the file may be closed then).
    """

    native_text: str
    image_regions: tuple[Region, ...]
    # Yields what an OCR engine accepts: an image file path or a BGR pixel array.
    render: Callable[[Region | None], str | np.ndarray]


class DocumentReader(ABC):
    """Reads one file type into its pages. Extend this to support a new file type.

    `file_type` is the label stored in `document_index`/`processing_metrics`/
    `confidence_metrics` for files this reader handles, so readers that should
    share statistics (e.g. all image formats) must share a `file_type`.
    `storage` declares where this file type's pages are persisted, and
    `processing_weight` how much heavier a file of this type is to process than
    a single image (used when sizing worker threads). Note the `document_index`
    and metrics tables constrain `file_type` to a fixed set, so a brand-new
    `file_type` also needs a schema migration.
    """

    file_type: str
    storage: PageStorage
    processing_weight: float = 1.0

    @abstractmethod
    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        """Yield the file's pages in order, or only the 1-based `page_number` if given."""


class PdfReader(DocumentReader):
    file_type = "pdf"
    storage = PdfPageStorage()
    # Multi-page and heavier to render than a single image.
    processing_weight = 1.5

    # An embedded image block only counts as a region worth OCR-ing once it covers
    # a non-trivial share of the page - small logos/rules shouldn't trigger it.
    MIN_IMAGE_AREA_FRACTION = 0.05

    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        import pymupdf

        try:
            doc = pymupdf.open(FsPath.extended(file_path))
        except (FileNotFoundError, pymupdf.FileNotFoundError) as exc:
            raise FileRemovedError(file_path) from exc
        except Exception as exc:  # noqa: BLE001 - pymupdf raises several types for a bad file
            raise CorruptedFileError(file_path, str(exc)) from exc

        with doc:
            if doc.needs_pass:
                raise PasswordProtectedError(file_path)
            try:
                indexes = range(doc.page_count) if page_number is None else [page_number - 1]
                for index in indexes:
                    page = doc[index]
                    yield ReadPage(
                        native_text=page.get_text(),
                        image_regions=PdfReader.significant_image_blocks(page),
                        render=PdfReader.renderer(page),
                    )
            except FileNotFoundError as exc:
                raise FileRemovedError(file_path) from exc
            except (pymupdf.FileDataError, pymupdf.mupdf.FzErrorFormat) as exc:
                raise CorruptedFileError(file_path, str(exc)) from exc

    @staticmethod
    def render_page_array(page: pymupdf.Page, clip: Region | None = None) -> np.ndarray:
        import cv2
        import numpy as np

        pixmap = page.get_pixmap(clip=clip)
        image_bytes = pixmap.tobytes("png")
        return cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)

    @staticmethod
    def significant_image_blocks(page: pymupdf.Page) -> tuple[Region, ...]:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return ()

        bboxes = []
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 1:
                continue
            x0, y0, x1, y1 = block["bbox"]
            area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            if area / page_area >= PdfReader.MIN_IMAGE_AREA_FRACTION:
                bboxes.append(block["bbox"])
        return tuple(bboxes)

    @staticmethod
    def renderer(page: pymupdf.Page) -> Callable[[Region | None], np.ndarray]:
        def render(region: Region | None) -> np.ndarray:
            return PdfReader.render_page_array(page, clip=region)

        return render


class ImageReader(DocumentReader):
    file_type = "image"
    storage = ImagePageStorage()

    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        yield ReadPage(
            native_text="",
            image_regions=(),
            render=lambda region: ImageReader.render_image(file_path),
        )

    @staticmethod
    def render_image(file_path: Path) -> str | np.ndarray:
        """What an OCR engine takes for this image: its path, or - when the path is too
        long for the engine's own file access - the decoded pixels."""
        if FsPath.extended(file_path) == file_path:
            return str(file_path)
        import cv2
        import numpy as np

        data = np.frombuffer(FsPath.extended(file_path).read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise CorruptedFileError(file_path)
        return image


class PngReader(ImageReader):
    """A .png file - identical to `ImageReader` today, split out as a hook for
    PNG-specific handling later (e.g. transparency)."""


class JpgReader(ImageReader):
    """A .jpg/.jpeg file - identical to `ImageReader` today, split out as a hook
    for JPEG-specific handling later."""
