"""OCR indexing pipeline: turns registered sources into searchable text.

Consumes the `sources` table (see `sources.py`) and, for every supported file
found under a source, runs PaddleOCR and writes the extracted text into
`document_index` plus a type-specific pages table (`pdf_pages`/`image_pages`).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

# Must be set before `paddleocr` is imported: skips its startup check for
# connectivity to the model hoster, which is slow and unnecessary once models
# are already cached locally. cv2/numpy/paddle/pymupdf/paddleocr are all
# imported lazily inside the functions that use them (not here at module
# level) since they're heavy - importing this module shouldn't pull in
# Paddle/OCR init as a side effect.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

if TYPE_CHECKING:
    import numpy as np
    import pymupdf
    from paddleocr import PaddleOCR

from vethuq_core.settings import is_gpu_enabled
from vethuq_core.sources import Source

_logger = logging.getLogger(__name__)

_PDF_EXTENSIONS = {".pdf"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_SUPPORTED_EXTENSIONS = _PDF_EXTENSIONS | _IMAGE_EXTENSIONS

# A page's native text layer counts as usable content once it clears both floors -
# short enough to reject a stray artifact (e.g. a scanner-stamped filename) that
# would otherwise mask a page that's actually a scanned image.
_MIN_NATIVE_TEXT_CHARS = 20
_MIN_NATIVE_TEXT_WORDS = 3

# An embedded image block only forces an OCR pass over its region once it covers
# a non-trivial share of the page - small logos/rules shouldn't trigger it.
_MIN_IMAGE_AREA_FRACTION = 0.05

# PaddleOCR model init is expensive; share one English-language engine per process.
# Constructed lazily so PDFs whose text is fully native never trigger it at all.
_engine: PaddleOCR | None = None


def _resolve_device(conn: sqlite3.Connection) -> str:
    """Pick the inference device honoring the user's GPU setting.

    GPU is opt-in and disabled by default (see `vethuq_core.settings`). When
    enabled, it's only actually used if this is a CUDA-capable PaddlePaddle
    build with a visible GPU - otherwise we fall back to CPU rather than
    erroring out, since enabling the setting on a CPU-only install (the
    common case) shouldn't break OCR.
    """
    if not is_gpu_enabled(conn):
        return "cpu"
    import paddle

    if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
        return "gpu"
    _logger.warning(
        "GPU is enabled in settings, but no CUDA-capable PaddlePaddle build/GPU "
        "was found. Falling back to CPU."
    )
    return "cpu"


def _get_engine(conn: sqlite3.Connection) -> PaddleOCR:
    global _engine
    if _engine is None:
        from paddleocr import PaddleOCR

        _engine = PaddleOCR(
            lang="en",
            device=_resolve_device(conn),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
    return _engine


@dataclass(frozen=True)
class PageResult:
    text: str
    confidence: float
    source: str  # 'native' | 'ocr' | 'mixed'


def _iter_supported_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        if path.suffix.lower() in _SUPPORTED_EXTENSIONS:
            yield path
        return
    for candidate in path.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in _SUPPORTED_EXTENSIONS:
            yield candidate


def _ocr_image_array(conn: sqlite3.Connection, image: str | np.ndarray) -> tuple[str, float]:
    engine = _get_engine(conn)
    result = engine.predict(image)
    page = result[0] if result else {}
    texts = page.get("rec_texts", [])
    scores = page.get("rec_scores", [])
    confidence = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(texts), confidence


def _ocr_image_file(conn: sqlite3.Connection, file_path: Path) -> PageResult:
    text, confidence = _ocr_image_array(conn, str(file_path))
    return PageResult(text=text, confidence=confidence, source="ocr")


def _render_page_array(
    page: pymupdf.Page, clip: tuple[float, float, float, float] | None = None
) -> np.ndarray:
    import cv2
    import numpy as np

    pixmap = page.get_pixmap(clip=clip)
    image_bytes = pixmap.tobytes("png")
    return cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)


def _is_native_text(text: str) -> bool:
    stripped = text.strip()
    return (
        len(stripped) >= _MIN_NATIVE_TEXT_CHARS
        and len(stripped.split()) >= _MIN_NATIVE_TEXT_WORDS
    )


def _significant_image_blocks(
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
        if area / page_area >= _MIN_IMAGE_AREA_FRACTION:
            bboxes.append(block["bbox"])
    return bboxes


def _ocr_pdf_page(conn: sqlite3.Connection, page: pymupdf.Page) -> PageResult:
    """Classify a page as native, scanned, or mixed and extract accordingly.

    Native text is read directly from the PDF's text layer with no OCR at all.
    OCR only runs over the page (or, for a mixed page, just the embedded image
    regions) when the native text layer can't account for the page's content.
    """
    native_text = page.get_text()
    image_blocks = _significant_image_blocks(page)

    if _is_native_text(native_text) and not image_blocks:
        return PageResult(text=native_text.strip(), confidence=1.0, source="native")

    if _is_native_text(native_text) and image_blocks:
        region_texts = []
        region_scores = []
        for bbox in image_blocks:
            text, confidence = _ocr_image_array(conn, _render_page_array(page, clip=bbox))
            region_texts.append(text)
            region_scores.append(confidence)
        combined_text = "\n".join([native_text.strip(), *region_texts])
        combined_confidence = sum(region_scores) / len(region_scores)
        return PageResult(text=combined_text, confidence=combined_confidence, source="mixed")

    text, confidence = _ocr_image_array(conn, _render_page_array(page))
    return PageResult(text=text, confidence=confidence, source="ocr")


def _ocr_pdf_file(conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
    import pymupdf

    with pymupdf.open(file_path) as doc:
        return [_ocr_pdf_page(conn, page) for page in doc]


def _upsert_document(
    conn: sqlite3.Connection, source_id: int, file_path: Path, file_type: str
) -> int:
    conn.execute(
        """
        INSERT INTO document_index (source_id, file_path, file_type, status)
        VALUES (?, ?, ?, 'pending')
        ON CONFLICT(file_path) DO UPDATE SET
            status = 'pending', error_message = NULL, indexed_at = NULL
        """,
        (source_id, str(file_path), file_type),
    )
    row = conn.execute(
        "SELECT id FROM document_index WHERE file_path = ?", (str(file_path),)
    ).fetchone()
    return row["id"]


def _mark_indexed(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute(
        "UPDATE document_index SET status = 'indexed', indexed_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), document_id),
    )


def _mark_error(conn: sqlite3.Connection, document_id: int, message: str) -> None:
    conn.execute(
        "UPDATE document_index SET status = 'error', error_message = ? WHERE id = ?",
        (message, document_id),
    )


@dataclass(frozen=True)
class DocumentResult:
    file_path: str
    status: str
    error_message: str | None
    confidence: float | None


def get_document_results(conn: sqlite3.Connection, source_id: int) -> list[DocumentResult]:
    """Return one result per document indexed under `source_id`, most recent first.

    `confidence` is the average across a document's pages (there's only one for
    an image; a PDF may have several), and is None for documents that aren't
    (yet) successfully indexed.
    """
    rows = conn.execute(
        "SELECT id, file_path, file_type, status, error_message "
        "FROM document_index WHERE source_id = ? ORDER BY file_path",
        (source_id,),
    ).fetchall()

    results = []
    for row in rows:
        confidence = None
        if row["status"] == "indexed":
            table = "pdf_pages" if row["file_type"] == "pdf" else "image_pages"
            scores = [
                page["confidence"]
                for page in conn.execute(
                    f"SELECT confidence FROM {table} WHERE document_id = ?", (row["id"],)
                )
            ]
            confidence = sum(scores) / len(scores) if scores else None
        results.append(
            DocumentResult(
                file_path=row["file_path"],
                status=row["status"],
                error_message=row["error_message"],
                confidence=confidence,
            )
        )
    return results


def run_ocr(
    conn: sqlite3.Connection, source: Source, *, only_new_files: bool = False
) -> list[str]:
    """Run OCR over supported files under `source` and index the results.

    Unsupported files are silently skipped. Per-file OCR failures are recorded
    on that file's `document_index` row (status='error') without aborting the
    rest of the source; `sources.status` reflects the overall outcome.

    When `only_new_files` is True, a file that already has a successful
    `document_index` row is left untouched - only new or previously failed
    files are (re)processed. Use this for a source that's already been
    indexed, to pick up files added since the last run without redoing OCR
    on everything. When False (the default), every supported file under the
    source is (re)processed unconditionally - appropriate for a source that's
    freshly added or reactivated after removal.

    Returns the paths of the files actually (re)processed in this call.
    """
    root = Path(source.path)
    had_error = False
    processed_paths: list[str] = []

    for file_path in _iter_supported_files(root):
        if only_new_files:
            existing = conn.execute(
                "SELECT status FROM document_index WHERE file_path = ?", (str(file_path),)
            ).fetchone()
            if existing is not None and existing["status"] == "indexed":
                continue

        file_type = "pdf" if file_path.suffix.lower() in _PDF_EXTENSIONS else "image"
        document_id = _upsert_document(conn, source.id, file_path, file_type)
        conn.commit()
        processed_paths.append(str(file_path))

        try:
            if file_type == "pdf":
                page_results = _ocr_pdf_file(conn, file_path)
                conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
                conn.executemany(
                    "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (document_id, page_number, page.text, page.confidence, page.source)
                        for page_number, page in enumerate(page_results, start=1)
                    ],
                )
            else:
                page = _ocr_image_file(conn, file_path)
                conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_id,))
                conn.execute(
                    "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (?, ?, ?)",
                    (document_id, page.text, page.confidence),
                )
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the source
            had_error = True
            _mark_error(conn, document_id, str(exc))
        else:
            _mark_indexed(conn, document_id)

        conn.commit()

    conn.execute(
        "UPDATE sources SET status = ?, last_scanned_at = ? WHERE id = ?",
        (
            "error" if had_error else "indexed",
            datetime.now(UTC).isoformat(),
            source.id,
        ),
    )
    conn.commit()
    return processed_paths
