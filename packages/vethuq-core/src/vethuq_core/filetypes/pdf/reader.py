"""Reader for `.pdf` files (the `type-pdf` file type)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq_core.fspath import FsPath
from vethuq_core.readers.errors import (
    CorruptedFileError,
    FileRemovedError,
    PasswordProtectedError,
)
from vethuq_core.readers.reader import DocumentReader, ReadPage, Region
from vethuq_core.readers.storage import PdfPageStorage

if TYPE_CHECKING:
    import numpy as np
    import pymupdf


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
