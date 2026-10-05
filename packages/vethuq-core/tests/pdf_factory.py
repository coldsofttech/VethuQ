"""Small PDFs built on the fly for unit tests, so no test depends on a fixture file.

`native` has a text layer, `scanned` is one page-sized image with no text, and `mixed` has both
(a text layer and a large embedded image). What the pages say is arbitrary: tests that run OCR
stub the engine, and the ones that read the text layer use `NATIVE_TEXT`.
"""

import io
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

NATIVE_TEXT = "Dear Sir, we write to confirm the agreed schedule for the annual review meeting."


def _image_bytes() -> bytes:
    """A page-sized picture with some structure (stripes), as PNG."""
    pixels = np.full((400, 300, 3), 255, np.uint8)
    pixels[::20] = (30, 30, 30)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "PNG")
    return buffer.getvalue()


def native(path: Path, pages: list[str] | None = None) -> Path:
    """A PDF whose pages carry `pages` (default: one page of `NATIVE_TEXT`) as text."""
    doc = pymupdf.open()
    for text in pages or [NATIVE_TEXT]:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def scanned(path: Path) -> Path:
    """A one-page PDF that is only a picture: no text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=_image_bytes())
    doc.save(path)
    doc.close()
    return path


def mixed(path: Path, text: str = NATIVE_TEXT) -> Path:
    """A one-page PDF with a text layer and a large embedded picture."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    page.insert_image(pymupdf.Rect(72, 150, 520, 700), stream=_image_bytes())
    doc.save(path)
    doc.close()
    return path
