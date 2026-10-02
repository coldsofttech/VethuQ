"""Readers that turn a file into its OCR'd pages."""

from __future__ import annotations

import codecs
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    import numpy as np
    import pymupdf

from vethuq_core.ocr.engine import Engine

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageResult:
    text: str
    confidence: float
    source: str  # 'native' | 'ocr' | 'mixed'
    ocr_engine: str | None = None
    language: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    encoding: str | None = None  # text files only: the character encoding decoded from

    def phase_columns(self) -> tuple[int, str]:
        """`(ocr_phase, ocr_angles)` to store for a page just read at 0 degrees.

        A native-text page is read straight from the PDF's text layer, not by an
        angle pass - so it's at phase 1 (quick) like any other page, with no angles
        recorded. Deeper phases skip it by its `source`, not by its phase number.
        """
        if self.source == "native":
            return 1, ""
        return 1, "0"


class Reader:
    """Reads one file type into its pages. Extend this to support a new file type.

    `file_type` is the label stored in `document_index`/`processing_metrics`/
    `confidence_metrics` for files this reader handles - most callers branch
    on it rather than on the reader itself, so readers that should share
    existing branches (e.g. all image formats today) must share a `file_type`.
    Persisting a new `file_type`'s pages still needs its own storage (see
    `Quick.process_file`/`Quick.run`) since `pdf_pages`/`image_pages` aren't generic.
    """

    file_type: str

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        raise NotImplementedError


class ImageReader(Reader):
    file_type = "image"

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return [ImageReader.ocr_file(conn, file_path)]

    @staticmethod
    def ocr_array(
        conn: sqlite3.Connection, image: str | np.ndarray
    ) -> tuple[str, float, int | None, int | None]:
        import cv2

        engine = Engine.get(conn)
        result = engine.predict(image)
        page = result[0] if result else {}
        texts = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        confidence = sum(scores) / len(scores) if scores else 0.0

        array = cv2.imread(image) if isinstance(image, str) else image
        if array is None:
            return "\n".join(texts), confidence, None, None
        height, width = array.shape[:2]
        return "\n".join(texts), confidence, width, height

    @staticmethod
    def ocr_file(conn: sqlite3.Connection, file_path: Path) -> PageResult:
        text, confidence, width, height = ImageReader.ocr_array(conn, str(file_path))
        return PageResult(
            text=text,
            confidence=confidence,
            source="ocr",
            ocr_engine=Engine.name(),
            language=Engine.LANGUAGE,
            image_width=width,
            image_height=height,
        )


class PdfReader(Reader):
    file_type = "pdf"

    # A page's native text layer counts as usable content once it clears both floors -
    # short enough to reject a stray artifact (e.g. a scanner-stamped filename) that
    # would otherwise mask a page that's actually a scanned image.
    MIN_NATIVE_TEXT_CHARS = 20
    MIN_NATIVE_TEXT_WORDS = 3

    # An embedded image block only forces an OCR pass over its region once it covers
    # a non-trivial share of the page - small logos/rules shouldn't trigger it.
    MIN_IMAGE_AREA_FRACTION = 0.05

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return PdfReader.ocr_file(conn, file_path)

    @staticmethod
    def render_page_array(
        page: pymupdf.Page, clip: tuple[float, float, float, float] | None = None
    ) -> np.ndarray:
        import cv2
        import numpy as np

        pixmap = page.get_pixmap(clip=clip)
        image_bytes = pixmap.tobytes("png")
        return cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)

    @staticmethod
    def is_native_text(text: str) -> bool:
        stripped = text.strip()
        return (
            len(stripped) >= PdfReader.MIN_NATIVE_TEXT_CHARS
            and len(stripped.split()) >= PdfReader.MIN_NATIVE_TEXT_WORDS
        )

    @staticmethod
    def significant_image_blocks(
        page: pymupdf.Page,
    ) -> list[tuple[float, float, float, float]]:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return []

        bboxes = []
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 1:
                continue
            x0, y0, x1, y1 = block["bbox"]
            area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            if area / page_area >= PdfReader.MIN_IMAGE_AREA_FRACTION:
                bboxes.append(block["bbox"])
        return bboxes

    @staticmethod
    def ocr_page(conn: sqlite3.Connection, page: pymupdf.Page) -> PageResult:
        """Classify a page as native, scanned, or mixed and extract accordingly.

        Native text is read directly from the PDF's text layer with no OCR at all.
        OCR only runs over the page (or, for a mixed page, just the embedded image
        regions) when the native text layer can't account for the page's content.
        """
        native_text = page.get_text()
        image_blocks = PdfReader.significant_image_blocks(page)

        if PdfReader.is_native_text(native_text) and not image_blocks:
            return PageResult(text=native_text.strip(), confidence=1.0, source="native")

        if PdfReader.is_native_text(native_text) and image_blocks:
            region_texts = []
            region_scores = []
            width = height = None
            for bbox in image_blocks:
                text, confidence, width, height = ImageReader.ocr_array(
                    conn, PdfReader.render_page_array(page, clip=bbox)
                )
                region_texts.append(text)
                region_scores.append(confidence)
            combined_text = "\n".join([native_text.strip(), *region_texts])
            combined_confidence = sum(region_scores) / len(region_scores)
            return PageResult(
                text=combined_text,
                confidence=combined_confidence,
                source="mixed",
                ocr_engine=Engine.name(),
                language=Engine.LANGUAGE,
                image_width=width,
                image_height=height,
            )

        text, confidence, width, height = ImageReader.ocr_array(
            conn, PdfReader.render_page_array(page)
        )
        return PageResult(
            text=text,
            confidence=confidence,
            source="ocr",
            ocr_engine=Engine.name(),
            language=Engine.LANGUAGE,
            image_width=width,
            image_height=height,
        )

    @staticmethod
    def ocr_file(conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        import pymupdf

        with pymupdf.open(file_path) as doc:
            return [PdfReader.ocr_page(conn, page) for page in doc]


class TxtReader(Reader):
    """A plain-text `.txt` file, read straight from disk - no OCR involved.

    The whole file is one "page" whose `source` is 'native' (the same label a PDF's
    text layer gets), so it's stored in `text_pages` and counted under the 'native'
    process type in the confidence stats. Only the character encoding has to be
    worked out, since `.txt` files carry no declaration of it.
    """

    file_type = "txt"

    # Byte-order marks, longest first so a UTF-32 LE BOM isn't mistaken for UTF-16 LE.
    _BOMS: tuple[tuple[bytes, str], ...] = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )

    # A last-resort single-byte decoding (any byte maps to something), used when the
    # bytes look like text but no encoding could be detected confidently.
    FALLBACK_ENCODING = "cp1252"
    FALLBACK_CONFIDENCE = 0.5

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return [TxtReader.read_file(file_path)]

    @staticmethod
    def decode(data: bytes) -> tuple[str, str, float]:
        """Decode `data` to `(text, encoding, confidence)`.

        A byte-order mark or a clean strict UTF-8 decode is exact (confidence 1.0).
        Otherwise the encoding is detected with `charset-normalizer`, with its own
        estimate of how well the bytes fit (`1 - chaos`) as the confidence. Raises
        `ValueError` for data that's evidently binary rather than text.
        """
        for bom, encoding in TxtReader._BOMS:
            if data.startswith(bom):
                return data.decode(encoding), encoding, 1.0

        try:
            return data.decode("utf-8"), "utf-8", 1.0
        except UnicodeDecodeError:
            pass

        from charset_normalizer import from_bytes

        match = from_bytes(data).best()
        if match is not None:
            return str(match), match.encoding, max(0.0, 1.0 - match.chaos)

        # Text in a single-byte encoding never contains NUL bytes; their presence (with
        # no UTF-16/32 reading of them) means this is some binary format, not text.
        if b"\x00" in data:
            raise ValueError("file is not plain text (contains binary data)")
        text = data.decode(TxtReader.FALLBACK_ENCODING, errors="replace")
        return text, TxtReader.FALLBACK_ENCODING, TxtReader.FALLBACK_CONFIDENCE

    @staticmethod
    def read_file(file_path: Path) -> PageResult:
        text, encoding, confidence = TxtReader.decode(file_path.read_bytes())
        return PageResult(
            text=text.strip(),
            confidence=confidence,
            source="native",
            encoding=encoding,
        )


class MdReader(Reader):
    """A Markdown `.md` file: its prose is read as text, and local images it embeds are OCR'd.

    The syntax is stripped (emphasis markers, link targets, HTML, fences' backticks) so
    search matches the words rather than the markup; code blocks, table cells, YAML
    front matter values and image alt text are kept. Each `![alt](path)` pointing at a
    local image file has that image OCR'd and its text appended - remote (`http://`,
    `data:`...) images are never fetched, so indexing stays offline. The file is one
    page: 'native' when it has no readable local image, 'mixed' when image text was added.
    """

    file_type = "md"

    # Images are only followed when the reader for their suffix is an `ImageReader`.
    _IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return [MdReader.read_file(conn, file_path)]

    @staticmethod
    def _parser() -> Any:
        from markdown_it import MarkdownIt
        from mdit_py_plugins.footnote import footnote_plugin
        from mdit_py_plugins.front_matter import front_matter_plugin

        return (
            MarkdownIt("commonmark")
            .enable(["table", "strikethrough"])
            .use(front_matter_plugin)
            .use(footnote_plugin)
        )

    @staticmethod
    def _flatten_front_matter(value: object, key: str | None = None) -> list[str]:
        """Front matter as `key: value` lines (lists as one comma-joined line)."""
        if isinstance(value, dict):
            lines: list[str] = []
            for child_key, child in value.items():
                lines.extend(MdReader._flatten_front_matter(child, str(child_key)))
            return lines
        if isinstance(value, list):
            if all(not isinstance(item, dict | list) for item in value):
                text = ", ".join(str(item) for item in value)
                return [f"{key}: {text}" if key else text]
            return [line for item in value for line in MdReader._flatten_front_matter(item, key)]
        if value is None:
            return []
        return [f"{key}: {value}" if key else str(value)]

    @staticmethod
    def extract(markdown: str) -> tuple[str, list[str]]:
        """`(plain_text, image_targets)` for Markdown source; targets are raw `![]()` paths."""
        import yaml

        lines: list[str] = []
        images: list[str] = []
        for token in MdReader._parser().parse(markdown):
            if token.type == "front_matter":
                try:
                    meta = yaml.safe_load(token.content)
                except yaml.YAMLError:
                    continue
                lines.extend(MdReader._flatten_front_matter(meta))
            elif token.type in ("fence", "code_block"):
                lines.append(token.content.rstrip("\n"))
            elif token.type == "inline":
                parts: list[str] = []
                for child in token.children or []:
                    if child.type in ("text", "code_inline"):
                        parts.append(child.content)
                    elif child.type in ("softbreak", "hardbreak"):
                        parts.append("\n")
                    elif child.type == "image":
                        parts.append(child.content)  # the alt text
                        images.append(str(child.attrGet("src") or ""))
                line = "".join(parts).strip()
                if line:
                    lines.append(line)
        return "\n".join(lines), images

    @staticmethod
    def resolve_image(markdown_path: Path, target: str) -> Path | None:
        """The local image file `target` names relative to `markdown_path`, else None."""
        target = target.strip()
        if not target:
            return None
        parts = urlsplit(target)
        # Any scheme or host (http:, data:, file:, //cdn...) is not a plain local path.
        # A single letter scheme is a Windows drive ("C:\\x.png"), which is local.
        if (parts.scheme and len(parts.scheme) > 1) or parts.netloc:
            return None
        raw = unquote(parts.path) if len(parts.scheme) != 1 else target
        if not raw:
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = markdown_path.parent / candidate
        if candidate.suffix.lower() not in MdReader._IMAGE_SUFFIXES or not candidate.is_file():
            return None
        return candidate

    @staticmethod
    def read_file(conn: sqlite3.Connection, file_path: Path) -> PageResult:
        markdown, encoding, confidence = TxtReader.decode(file_path.read_bytes())
        text, targets = MdReader.extract(markdown)

        confidences = [confidence]
        texts = [text]
        seen: set[Path] = set()
        for target in targets:
            image_path = MdReader.resolve_image(file_path, target)
            if image_path is None or image_path in seen:
                continue
            seen.add(image_path)
            try:
                image = ImageReader.ocr_file(conn, image_path)
            except Exception:
                _logger.warning("Could not OCR %s embedded in %s", image_path, file_path)
                continue
            if image.text.strip():
                texts.append(image.text.strip())
                confidences.append(image.confidence)

        return PageResult(
            text="\n".join(part for part in texts if part).strip(),
            confidence=sum(confidences) / len(confidences),
            source="mixed" if len(texts) > 1 else "native",
            ocr_engine=Engine.name() if len(texts) > 1 else None,
            language=Engine.LANGUAGE if len(texts) > 1 else None,
            encoding=encoding,
        )


class PngReader(ImageReader):
    """A .png file - identical to `ImageReader` today, split out as a hook for
    PNG-specific handling later (e.g. transparency)."""


class JpgReader(ImageReader):
    """A .jpg/.jpeg file - identical to `ImageReader` today, split out as a hook
    for JPEG-specific handling later."""


class Readers:
    """The registered readers, by file suffix."""

    _BY_SUFFIX: dict[str, Reader] = {
        ".pdf": PdfReader(),
        ".png": PngReader(),
        ".jpg": JpgReader(),
        ".jpeg": JpgReader(),
        ".txt": TxtReader(),
        ".md": MdReader(),
        ".markdown": MdReader(),
    }

    @staticmethod
    def for_path(file_path: Path) -> Reader:
        return Readers._BY_SUFFIX[file_path.suffix.lower()]

    @staticmethod
    def is_supported(file_path: Path) -> bool:
        return file_path.suffix.lower() in Readers._BY_SUFFIX

    @staticmethod
    def iter_files(path: Path) -> Iterator[Path]:
        if path.is_file():
            if Readers.is_supported(path):
                yield path
            return
        for candidate in path.rglob("*"):
            if candidate.is_file() and Readers.is_supported(candidate):
                yield candidate

    @staticmethod
    def new_file_type_counts() -> dict[str, int]:
        """A zeroed `{file_type: count}` for every file type registered readers handle."""
        return dict.fromkeys((reader.file_type for reader in Readers._BY_SUFFIX.values()), 0)
