"""OCR indexing pipeline: turns registered sources into searchable text.

Consumes the `sources` table (see `sources.py`) and, for every supported file
found under a source, runs PaddleOCR and writes the extracted text into
`document_index` plus a type-specific pages table (`pdf_pages`/`image_pages`).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

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

from vethuq_core.settings import (
    THREAD_WORKERS_AUTO,
    THREAD_WORKERS_MAX,
    get_ocr_retry_attempts,
    get_thread_workers,
    is_gpu_enabled,
)
from vethuq_core.sources import Source

_logger = logging.getLogger(__name__)

_OCR_LANGUAGE = "en"

# A page's native text layer counts as usable content once it clears both floors -
# short enough to reject a stray artifact (e.g. a scanner-stamped filename) that
# would otherwise mask a page that's actually a scanned image.
_MIN_NATIVE_TEXT_CHARS = 20
_MIN_NATIVE_TEXT_WORDS = 3

# An embedded image block only forces an OCR pass over its region once it covers
# a non-trivial share of the page - small logos/rules shouldn't trigger it.
_MIN_IMAGE_AREA_FRACTION = 0.05

# PaddleOCR model init is expensive; share one English-language engine per
# *thread* rather than per process - a run with N worker threads (see
# `resolve_thread_workers`) gets N engine instances so OCR inference itself
# actually parallelizes, at the cost of N times the model memory footprint.
# Constructed lazily so PDFs whose text is fully native never trigger it at all.
_engine_local = threading.local()


def _ocr_engine_name() -> str:
    return f"paddleocr {_package_version('paddleocr')}"


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
    engine = getattr(_engine_local, "engine", None)
    if engine is None:
        from paddleocr import PaddleOCR

        engine = PaddleOCR(
            lang=_OCR_LANGUAGE,
            device=_resolve_device(conn),
            # Corrects whole-page rotation (0/90/180/270) and per-line rotated
            # text so scanned/photographed pages that aren't perfectly upright
            # still OCR correctly. use_doc_unwarping (perspective/warp, not
            # angle, correction) stays off - it's a heavier pass and unrelated
            # to angle handling.
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            enable_mkldnn=False,
        )
        _engine_local.engine = engine
    return engine


@dataclass(frozen=True)
class PageResult:
    text: str
    confidence: float
    source: str  # 'native' | 'ocr' | 'mixed'
    ocr_engine: str | None = None
    language: str | None = None
    image_width: int | None = None
    image_height: int | None = None


def _iter_supported_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        if path.suffix.lower() in _READERS:
            yield path
        return
    for candidate in path.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in _READERS:
            yield candidate


def _ocr_image_array(
    conn: sqlite3.Connection, image: str | np.ndarray
) -> tuple[str, float, int | None, int | None]:
    import cv2

    engine = _get_engine(conn)
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


def _ocr_image_file(conn: sqlite3.Connection, file_path: Path) -> PageResult:
    text, confidence, width, height = _ocr_image_array(conn, str(file_path))
    return PageResult(
        text=text,
        confidence=confidence,
        source="ocr",
        ocr_engine=_ocr_engine_name(),
        language=_OCR_LANGUAGE,
        image_width=width,
        image_height=height,
    )


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
        len(stripped) >= _MIN_NATIVE_TEXT_CHARS and len(stripped.split()) >= _MIN_NATIVE_TEXT_WORDS
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
        width = height = None
        for bbox in image_blocks:
            text, confidence, width, height = _ocr_image_array(
                conn, _render_page_array(page, clip=bbox)
            )
            region_texts.append(text)
            region_scores.append(confidence)
        combined_text = "\n".join([native_text.strip(), *region_texts])
        combined_confidence = sum(region_scores) / len(region_scores)
        return PageResult(
            text=combined_text,
            confidence=combined_confidence,
            source="mixed",
            ocr_engine=_ocr_engine_name(),
            language=_OCR_LANGUAGE,
            image_width=width,
            image_height=height,
        )

    text, confidence, width, height = _ocr_image_array(conn, _render_page_array(page))
    return PageResult(
        text=text,
        confidence=confidence,
        source="ocr",
        ocr_engine=_ocr_engine_name(),
        language=_OCR_LANGUAGE,
        image_width=width,
        image_height=height,
    )


def _ocr_pdf_file(conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
    import pymupdf

    with pymupdf.open(file_path) as doc:
        return [_ocr_pdf_page(conn, page) for page in doc]


class Reader:
    """Reads one file type into its pages. Extend this to support a new file type.

    `file_type` is the label stored in `document_index`/`processing_metrics`/
    `confidence_metrics` for files this reader handles - most callers branch
    on it rather than on the reader itself, so readers that should share
    existing branches (e.g. all image formats today) must share a `file_type`.
    Persisting a new `file_type`'s pages still needs its own storage (see
    `_process_file`/`run_ocr`) since `pdf_pages`/`image_pages` aren't generic.
    """

    file_type: str

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        raise NotImplementedError


class PdfReader(Reader):
    file_type = "pdf"

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return _ocr_pdf_file(conn, file_path)


class ImageReader(Reader):
    file_type = "image"

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return [_ocr_image_file(conn, file_path)]


class PngReader(ImageReader):
    """A .png file - identical to `ImageReader` today, split out as a hook for
    PNG-specific handling later (e.g. transparency)."""


class JpgReader(ImageReader):
    """A .jpg/.jpeg file - identical to `ImageReader` today, split out as a hook
    for JPEG-specific handling later."""


_READERS: dict[str, Reader] = {
    ".pdf": PdfReader(),
    ".png": PngReader(),
    ".jpg": JpgReader(),
    ".jpeg": JpgReader(),
}


def new_file_type_counts() -> dict[str, int]:
    """A zeroed `{file_type: count}` for every file type registered readers handle."""
    return dict.fromkeys((reader.file_type for reader in _READERS.values()), 0)


_CHECKSUM_CHUNK_BYTES = 1024 * 1024


def _compute_checksum(file_path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents, read in chunks."""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHECKSUM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_duplicate_original(
    conn: sqlite3.Connection, checksum: str, document_id: int
) -> int | None:
    """Return the id of the original document `document_id` duplicates, if any.

    An "original" is the earliest-indexed document with matching content
    (same checksum) that isn't itself a duplicate of something else -
    duplicates always link directly to the root original, never to a chain.
    """
    row = conn.execute(
        "SELECT id FROM document_index "
        "WHERE checksum = ? AND id != ? AND duplicate_of_id IS NULL AND status = 'indexed' "
        "ORDER BY id ASC LIMIT 1",
        (checksum, document_id),
    ).fetchone()
    return row["id"] if row is not None else None


def _has_content_changed(file_path: Path, existing: sqlite3.Row) -> bool:
    """Return whether `file_path`'s content differs from its `document_index` row.

    A file's mtime and size are checked first - if neither moved since it was
    last indexed, its content is assumed unchanged and the (expensive) full
    checksum is skipped entirely. Only when mtime or size differ is the
    checksum recomputed and compared, to confirm this is an actual content
    change rather than e.g. a touch that left the bytes alone.
    """
    stat = file_path.stat()
    if stat.st_mtime == existing["mtime"] and stat.st_size == existing["file_size_bytes"]:
        return False
    return _compute_checksum(file_path) != existing["checksum"]


def _upsert_document(
    conn: sqlite3.Connection, source_id: int, file_path: Path, file_type: str
) -> tuple[int, int | None]:
    """Insert/reset a document's `document_index` row and check it for duplicates.

    Returns `(document_id, duplicate_of_id)` - `duplicate_of_id` is the id of
    the original document this one's content (by checksum) already matches,
    or None if this document is new/unique content.

    If this document's checksum is changing (its content was modified since
    it was last indexed) and other documents were deduped against its old
    content, the earliest of them is promoted to take over as the original
    for that old content first - see `_promote_surviving_duplicate` - so
    they keep reusing the OCR text that actually matches their (unchanged)
    bytes instead of silently inheriting this document's new, unrelated one.
    """
    started_at = datetime.now(UTC).isoformat()
    stat = file_path.stat()
    file_size_bytes = stat.st_size
    mtime = stat.st_mtime
    checksum = _compute_checksum(file_path)

    existing = conn.execute(
        "SELECT id, checksum FROM document_index WHERE file_path = ?", (str(file_path),)
    ).fetchone()
    if existing is not None and existing["checksum"] != checksum:
        from vethuq_core.sources import _promote_surviving_duplicate

        _promote_surviving_duplicate(conn, existing["id"], set())

    conn.execute(
        """
        INSERT INTO document_index
            (source_id, file_path, file_type, status, started_at, file_size_bytes, checksum, mtime)
        VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            status = 'pending', error_message = NULL, indexed_at = NULL,
            started_at = excluded.started_at, completed_at = NULL,
            file_size_bytes = excluded.file_size_bytes, checksum = excluded.checksum,
            mtime = excluded.mtime, duplicate_of_id = NULL
        """,
        (source_id, str(file_path), file_type, started_at, file_size_bytes, checksum, mtime),
    )
    row = conn.execute(
        "SELECT id FROM document_index WHERE file_path = ?", (str(file_path),)
    ).fetchone()
    document_id = row["id"]
    return document_id, _find_duplicate_original(conn, checksum, document_id)


def _reconcile_renamed_and_removed_files(
    conn: sqlite3.Connection, source: Source, disk_files: list[Path]
) -> set[str]:
    """Detect files renamed/moved within `source`, and files missing from it.

    Compares `source`'s tracked (non-'removed') `document_index` rows
    against `disk_files` (every supported file currently found under this
    source). A brand-new path whose checksum exactly matches a tracked path
    that's no longer on disk is treated as that file renamed or moved: the
    existing row's `file_path` (and mtime/size) is updated in place, with no
    OCR re-run, rather than indexing it as an unrelated new file and leaving
    the old row to be purged as removed.

    When more than one candidate shares a checksum (e.g. two files with
    identical content, one deleted and one renamed), pairing is done in a
    deterministic but otherwise arbitrary order (tracked rows by id, new
    paths alphabetically) rather than left unmatched. This is safe even
    when "wrong": whichever row ends up representing that content, a
    document that owned OCR pages other rows were deduped against still
    hands them off correctly via `_promote_surviving_duplicate` once it's
    actually purged, so no OCR text is ever lost or misattributed.

    A tracked path that's gone missing and isn't claimed by a rename is
    marked 'removed' (with `removed_at` set) so `purge_expired_removed_documents`
    can clean it up after the retention window, promoting a surviving
    duplicate first if other documents had been deduped against it.

    Returns the set of new on-disk paths (as strings) claimed by a rename,
    so the caller can skip (re-)indexing them.
    """
    disk_path_strs = {str(path) for path in disk_files}
    tracked = conn.execute(
        "SELECT id, file_path, checksum FROM document_index "
        "WHERE source_id = ? AND status != 'removed'",
        (source.id,),
    ).fetchall()
    tracked_paths = {row["file_path"] for row in tracked}

    missing_rows = [row for row in tracked if row["file_path"] not in disk_path_strs]
    new_paths = sorted(disk_path_strs - tracked_paths)

    claimed_paths: set[str] = set()
    claimed_row_ids: set[int] = set()

    if missing_rows and new_paths:
        new_checksums = {path: _compute_checksum(Path(path)) for path in new_paths}
        missing_by_checksum: dict[str, list[sqlite3.Row]] = {}
        for row in sorted(missing_rows, key=lambda r: r["id"]):
            missing_by_checksum.setdefault(row["checksum"], []).append(row)
        new_by_checksum: dict[str, list[str]] = {}
        for path in new_paths:
            new_by_checksum.setdefault(new_checksums[path], []).append(path)

        for checksum, rows in missing_by_checksum.items():
            matching_paths = new_by_checksum.get(checksum)
            if not matching_paths:
                continue
            for row, new_path in zip(rows, matching_paths, strict=False):
                stat = Path(new_path).stat()
                conn.execute(
                    "UPDATE document_index SET file_path = ?, mtime = ?, "
                    "file_size_bytes = ? WHERE id = ?",
                    (new_path, stat.st_mtime, stat.st_size, row["id"]),
                )
                claimed_paths.add(new_path)
                claimed_row_ids.add(row["id"])

    removed_at = datetime.now(UTC).isoformat()
    for row in missing_rows:
        if row["id"] in claimed_row_ids:
            continue
        conn.execute(
            "UPDATE document_index SET status = 'removed', removed_at = ? WHERE id = ?",
            (removed_at, row["id"]),
        )

    return claimed_paths


def _mark_indexed(conn: sqlite3.Connection, document_id: int) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE document_index SET status = 'indexed', indexed_at = ?, completed_at = ? "
        "WHERE id = ?",
        (now, now, document_id),
    )


def _mark_duplicate(conn: sqlite3.Connection, document_id: int, original_id: int) -> None:
    """Mark a document as indexed via a checksum match instead of running OCR on it."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE document_index SET status = 'indexed', duplicate_of_id = ?, "
        "indexed_at = ?, completed_at = ? WHERE id = ?",
        (original_id, now, now, document_id),
    )


def _mark_error(conn: sqlite3.Connection, document_id: int, message: str) -> None:
    conn.execute(
        "UPDATE document_index SET status = 'error', error_message = ?, completed_at = ? "
        "WHERE id = ?",
        (message, datetime.now(UTC).isoformat(), document_id),
    )


def _update_processing_metrics(conn: sqlite3.Connection, document_id: int, file_type: str) -> None:
    """Fold one freshly-indexed document's duration/memory/cpu into `processing_metrics`'s
    running averages.

    Called only for successfully indexed documents - a failed document has a
    duration that doesn't reflect a full OCR pass, so it would skew the
    averages `vethuq index run` uses to estimate ETAs.
    """
    doc = conn.execute(
        "SELECT started_at, completed_at, peak_memory_mb, cpu_percent, file_size_bytes "
        "FROM document_index WHERE id = ?",
        (document_id,),
    ).fetchone()
    duration = (
        datetime.fromisoformat(doc["completed_at"]) - datetime.fromisoformat(doc["started_at"])
    ).total_seconds()
    peak_memory_mb = doc["peak_memory_mb"] or 0.0
    cpu_percent = doc["cpu_percent"] or 0.0
    size_bucket = _size_bucket(doc["file_size_bytes"] or 0)

    now = datetime.now(UTC).isoformat()
    existing = conn.execute(
        "SELECT document_count, avg_duration_seconds, "
        "avg_peak_memory_mb, avg_cpu_percent FROM processing_metrics "
        "WHERE file_type = ? AND size_bucket = ?",
        (file_type, size_bucket),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO processing_metrics "
            "(file_type, size_bucket, document_count, avg_duration_seconds, avg_peak_memory_mb, "
            "avg_cpu_percent, updated_at) "
            "VALUES (?, ?, 1, ?, ?, ?, ?)",
            (file_type, size_bucket, duration, peak_memory_mb, cpu_percent, now),
        )
        return

    new_count = existing["document_count"] + 1
    avg_duration = (
        existing["avg_duration_seconds"] + (duration - existing["avg_duration_seconds"]) / new_count
    )
    avg_peak_memory_mb = (
        existing["avg_peak_memory_mb"]
        + (peak_memory_mb - existing["avg_peak_memory_mb"]) / new_count
    )
    avg_cpu_percent = (
        existing["avg_cpu_percent"] + (cpu_percent - existing["avg_cpu_percent"]) / new_count
    )
    conn.execute(
        "UPDATE processing_metrics SET document_count = ?, avg_duration_seconds = ?, "
        "avg_peak_memory_mb = ?, avg_cpu_percent = ?, updated_at = ? "
        "WHERE file_type = ? AND size_bucket = ?",
        (
            new_count,
            avg_duration,
            avg_peak_memory_mb,
            avg_cpu_percent,
            now,
            file_type,
            size_bucket,
        ),
    )


def _update_confidence_metrics(conn: sqlite3.Connection, document_id: int, file_type: str) -> None:
    """Fold one freshly-indexed document's pages into `confidence_metrics`'s running
    averages, grouped independently by (file_type, process_type).

    Native pages run near-100% confidence while OCR/mixed pages don't, so
    blending them into a single average would dilute the OCR/mixed signal -
    tracking each process_type separately keeps them meaningful.
    """
    if file_type == "pdf":
        pages = conn.execute(
            "SELECT confidence, source FROM pdf_pages WHERE document_id = ?", (document_id,)
        ).fetchall()
    else:
        pages = conn.execute(
            "SELECT confidence FROM image_pages WHERE document_id = ?", (document_id,)
        ).fetchall()
    if not pages:
        return

    by_process_type: dict[str, list[float]] = {}
    for page in pages:
        process_type = page["source"] if file_type == "pdf" else "ocr"
        by_process_type.setdefault(process_type, []).append(page["confidence"])

    now = datetime.now(UTC).isoformat()
    for process_type, confidences in by_process_type.items():
        existing = conn.execute(
            "SELECT page_count, avg_confidence FROM confidence_metrics "
            "WHERE file_type = ? AND process_type = ?",
            (file_type, process_type),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO confidence_metrics "
                "(file_type, process_type, page_count, avg_confidence, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    file_type,
                    process_type,
                    len(confidences),
                    sum(confidences) / len(confidences),
                    now,
                ),
            )
            continue

        new_count = existing["page_count"] + len(confidences)
        avg_confidence = (
            existing["avg_confidence"] * existing["page_count"] + sum(confidences)
        ) / new_count
        conn.execute(
            "UPDATE confidence_metrics SET page_count = ?, avg_confidence = ?, updated_at = ? "
            "WHERE file_type = ? AND process_type = ?",
            (new_count, avg_confidence, now, file_type, process_type),
        )


@dataclass(frozen=True)
class DocumentResult:
    file_path: str
    status: str
    error_message: str | None
    confidence: float | None
    started_at: str | None
    completed_at: str | None
    duration: float | None
    duplicate_of_path: str | None


def get_document_results(conn: sqlite3.Connection, source_id: int) -> list[DocumentResult]:
    """Return one result per document indexed under `source_id`, most recent first.

    `confidence` is the average across a document's pages (there's only one for
    an image; a PDF may have several), and is None for documents that aren't
    (yet) successfully indexed. For a duplicate (`duplicate_of_path` is not
    None), the pages - and so the confidence - are the original's, since a
    duplicate has none of its own. `duration` (in seconds) is derived from
    `started_at`/`completed_at` and is None while a document is still pending.
    """
    rows = conn.execute(
        "SELECT di.id AS id, di.file_path AS file_path, di.file_type AS file_type, "
        "di.status AS status, di.error_message AS error_message, "
        "di.started_at AS started_at, di.completed_at AS completed_at, "
        "COALESCE(di.duplicate_of_id, di.id) AS canonical_id, "
        "orig.file_path AS duplicate_of_path "
        "FROM document_index di "
        "LEFT JOIN document_index orig ON orig.id = di.duplicate_of_id "
        "WHERE di.source_id = ? ORDER BY di.file_path",
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
                    f"SELECT confidence FROM {table} WHERE document_id = ?",
                    (row["canonical_id"],),
                )
            ]
            confidence = sum(scores) / len(scores) if scores else None

        duration = None
        if row["started_at"] and row["completed_at"]:
            duration = (
                datetime.fromisoformat(row["completed_at"])
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()

        results.append(
            DocumentResult(
                file_path=row["file_path"],
                status=row["status"],
                error_message=row["error_message"],
                confidence=confidence,
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                duration=duration,
                duplicate_of_path=row["duplicate_of_path"],
            )
        )
    return results


def _iter_pending_files(
    conn: sqlite3.Connection,
    source: Source,
    *,
    only_new_files: bool = False,
    only_failed: bool = False,
) -> Iterator[tuple[Path, str]]:
    """Yield `(file_path, file_type)` for files `run_ocr` would actually (re)process.

    Mirrors the skip logic in `run_ocr` so callers (e.g. progress/ETA
    reporting) can size a run before starting it.
    """
    root = Path(source.path)
    for file_path in _iter_supported_files(root):
        existing = None
        if only_new_files or only_failed:
            existing = conn.execute(
                "SELECT status, mtime, file_size_bytes, checksum FROM document_index "
                "WHERE file_path = ?",
                (str(file_path),),
            ).fetchone()
        if only_failed:
            if existing is None or existing["status"] != "error":
                continue
        elif (
            only_new_files
            and existing is not None
            and existing["status"] == "indexed"
            and not _has_content_changed(file_path, existing)
        ):
            continue
        file_type = _READERS[file_path.suffix.lower()].file_type
        yield file_path, file_type


def pending_file_count(
    conn: sqlite3.Connection,
    source: Source,
    *,
    only_new_files: bool = False,
    only_failed: bool = False,
) -> int:
    """Count the files `run_ocr` would actually (re)process for `source`."""
    return sum(
        1
        for _ in _iter_pending_files(
            conn, source, only_new_files=only_new_files, only_failed=only_failed
        )
    )


def pending_file_type_counts(
    conn: sqlite3.Connection,
    source: Source,
    *,
    only_new_files: bool = False,
    only_failed: bool = False,
) -> dict[str, int]:
    """Like `pending_file_count`, but broken down by file_type ('pdf'/'image').

    Used to weight ETA estimates by each file type's own average OCR
    duration (`processing_metrics`), since a source's remaining files may be
    a mix of pdfs and images that OCR at very different speeds.
    """
    counts = new_file_type_counts()
    for _, file_type in _iter_pending_files(
        conn, source, only_new_files=only_new_files, only_failed=only_failed
    ):
        counts[file_type] += 1
    return counts


_ENGINE_FOOTPRINT_MB = 700  # rough resident memory of one PaddleOCR CPU engine instance
_PDF_WEIGHT = 1.5  # a pending set that's mostly PDFs costs more per worker than mostly images
_CPU_BUSY_THRESHOLD = 70.0
_MEMORY_BUSY_THRESHOLD = 80.0

# Keep these in sync with the literal byte thresholds in db.py's version-16
# migration, which buckets historical document_index rows the same way.
_SIZE_BUCKET_SMALL_MAX_BYTES = 500_000
_SIZE_BUCKET_MEDIUM_MAX_BYTES = 3_000_000


def _size_bucket(file_size_bytes: int) -> str:
    """Classify a file's size into the coarse bucket `processing_metrics` is keyed by."""
    if file_size_bytes < _SIZE_BUCKET_SMALL_MAX_BYTES:
        return "small"
    if file_size_bytes < _SIZE_BUCKET_MEDIUM_MAX_BYTES:
        return "medium"
    return "large"


def resolve_thread_workers(conn: sqlite3.Connection, pending_type_counts: dict[str, int]) -> int:
    """Resolve the effective worker count for a run from the `thread_workers` setting.

    '0' disables concurrency entirely - the caller should process its file
    list sequentially, in its own thread, with no pool at all. '1'-'8' is
    used as given. 'auto' sizes workers dynamically from current CPU/memory
    headroom and the pending file mix - see `_auto_worker_count`. Either
    way, the result never exceeds the number of pending files, since
    starting more workers than there is work to hand them doesn't help.
    """
    total_pending = sum(pending_type_counts.values())
    setting = get_thread_workers(conn)
    workers = (
        _auto_worker_count(pending_type_counts, total_pending)
        if setting == THREAD_WORKERS_AUTO
        else int(setting)
    )
    return min(workers, total_pending) if total_pending and workers else workers


def _auto_worker_count(pending_type_counts: dict[str, int], total_pending: int) -> int:
    """Pick a worker count that uses headroom without pushing CPU/memory to their limit.

    Each worker loads its own OCR engine (see `_get_engine`), so the ceiling
    is set by whichever is scarcer: free CPU capacity, or free memory divided
    by one engine's rough footprint (`_ENGINE_FOOTPRINT_MB`). A pending set
    that's mostly PDFs (multi-page, heavier to render/OCR than a single
    image) scales the result down further. Already-busy CPU or memory (past
    `_CPU_BUSY_THRESHOLD`/`_MEMORY_BUSY_THRESHOLD`) caps it at a single
    worker rather than trying to squeeze more out of an already-loaded
    machine.
    """
    if total_pending == 0:
        return 1

    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    if cpu_percent >= _CPU_BUSY_THRESHOLD or memory.percent >= _MEMORY_BUSY_THRESHOLD:
        return 1

    cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 1
    cpu_headroom = max(1, round(cpu_count * (1 - cpu_percent / 100)))
    memory_headroom = max(1, int(memory.available / (1024 * 1024) / _ENGINE_FOOTPRINT_MB))

    pdf_share = pending_type_counts.get("pdf", 0) / total_pending
    weight = 1 + pdf_share * (_PDF_WEIGHT - 1)
    workers = max(1, round(min(cpu_headroom, memory_headroom) / weight))

    return min(workers, THREAD_WORKERS_MAX, total_pending)


def run_ocr(
    conn: sqlite3.Connection,
    source: Source,
    *,
    only_new_files: bool = False,
    only_failed: bool = False,
    on_file_done: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[str]:
    """Run OCR over supported files under `source` and index the results.

    Unsupported files are silently skipped. Per-file OCR failures are recorded
    on that file's `document_index` row (status='error') without aborting the
    rest of the source; `sources.status` reflects the overall outcome.

    When `only_new_files` is True, a file that already has a successful
    `document_index` row is left untouched unless its content has changed
    since - checked via mtime/size first, falling back to a full checksum
    comparison when either moved. A changed file is treated as modified and
    (re)processed just like a new one. Use this for a source that's already
    been indexed, to pick up files added or edited since the last run
    without redoing OCR on everything else. When False (the default), every
    supported file under the source is (re)processed unconditionally -
    appropriate for a source that's freshly added or reactivated after
    removal.

    When `only_failed` is True, only files whose `document_index` row has
    status='error' are (re)processed - new and already-indexed files are
    left untouched. Use this to retry failures without touching anything
    else. Takes precedence over `only_new_files` if both are set.

    When `only_new_files` is True (and `only_failed` is False), this also
    reconciles the source's tracked files against what's actually on disk
    before processing anything - see `_reconcile_renamed_and_removed_files`.
    A file that was renamed/moved within the source is detected by content
    and has its `document_index` row updated in place rather than being
    reprocessed as new; a tracked file that's gone missing (and wasn't
    claimed by a rename) is marked 'removed' for later cleanup by
    `purge_expired_removed_documents`.

    `on_file_done`, when given, is called with a file's path immediately after
    it's (re)processed - used to report progress. `should_stop`, when given,
    is checked before each file and stops the source early (leaving remaining
    files untouched) if it returns True.

    Returns the paths of the files actually (re)processed in this call.
    """
    root = Path(source.path)
    had_error = False
    processed_paths: list[str] = []
    disk_files = list(_iter_supported_files(root))

    renamed_paths: set[str] = set()
    if only_new_files and not only_failed:
        renamed_paths = _reconcile_renamed_and_removed_files(conn, source, disk_files)
        conn.commit()
        for new_path in sorted(renamed_paths):
            processed_paths.append(new_path)
            if on_file_done is not None:
                on_file_done(new_path)

    for file_path in disk_files:
        if should_stop is not None and should_stop():
            break
        if str(file_path) in renamed_paths:
            continue

        existing = None
        if only_new_files or only_failed:
            existing = conn.execute(
                "SELECT status, mtime, file_size_bytes, checksum FROM document_index "
                "WHERE file_path = ?",
                (str(file_path),),
            ).fetchone()
        if only_failed:
            if existing is None or existing["status"] != "error":
                continue
        elif (
            only_new_files
            and existing is not None
            and existing["status"] == "indexed"
            and not _has_content_changed(file_path, existing)
        ):
            continue

        file_type = _READERS[file_path.suffix.lower()].file_type
        document_id, duplicate_of_id = _upsert_document(conn, source.id, file_path, file_type)
        conn.commit()
        processed_paths.append(str(file_path))

        if duplicate_of_id is not None:
            # Identical content already indexed under `duplicate_of_id` - link to
            # it and skip OCR entirely rather than redoing the same work.
            _mark_duplicate(conn, document_id, duplicate_of_id)
            conn.commit()
            if on_file_done is not None:
                on_file_done(str(file_path))
            continue

        process = psutil.Process()
        process.cpu_percent(interval=None)  # prime; the next call reports usage since now
        mem_before = process.memory_info().rss

        reader = _READERS[file_path.suffix.lower()]
        max_attempts = 1 + get_ocr_retry_attempts(conn)
        attempt = 0
        last_exc: Exception | None = None
        succeeded = False
        while attempt < max_attempts and not succeeded:
            attempt += 1
            try:
                pages = reader.ocr(conn, file_path)
                if file_type == "pdf":
                    conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
                    conn.executemany(
                        "INSERT INTO pdf_pages "
                        "(document_id, page_number, ocr_text, confidence, source, "
                        "ocr_engine, language, image_width, image_height) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (
                                document_id,
                                page_number,
                                page.text,
                                page.confidence,
                                page.source,
                                page.ocr_engine,
                                page.language,
                                page.image_width,
                                page.image_height,
                            )
                            for page_number, page in enumerate(pages, start=1)
                        ],
                    )
                else:
                    page = pages[0]
                    conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_id,))
                    conn.execute(
                        "INSERT INTO image_pages "
                        "(document_id, ocr_text, confidence, ocr_engine, language, "
                        "image_width, image_height) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            document_id,
                            page.text,
                            page.confidence,
                            page.ocr_engine,
                            page.language,
                            page.image_width,
                            page.image_height,
                        ),
                    )
            except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the source
                last_exc = exc
            else:
                succeeded = True

        peak_memory_mb = max(mem_before, process.memory_info().rss) / (1024 * 1024)
        cpu_percent = process.cpu_percent(interval=None)
        conn.execute(
            "UPDATE document_index SET retry_count = ?, peak_memory_mb = ?, cpu_percent = ? "
            "WHERE id = ?",
            (attempt - 1, peak_memory_mb, cpu_percent, document_id),
        )

        if not succeeded:
            had_error = True
            _mark_error(conn, document_id, str(last_exc))
        else:
            _mark_indexed(conn, document_id)
            _update_processing_metrics(conn, document_id, file_type)
            _update_confidence_metrics(conn, document_id, file_type)

        conn.commit()
        if on_file_done is not None:
            on_file_done(str(file_path))

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


@dataclass(frozen=True)
class _PendingFile:
    source: Source
    path: Path
    file_type: str


def _process_file(
    conn: sqlite3.Connection,
    source: Source,
    file_path: Path,
    file_type: str,
    *,
    db_lock: threading.Lock,
) -> bool:
    """Index one file: upsert its row, dedupe by checksum, and OCR it if new content.

    Returns whether it succeeded (False on an OCR failure recorded as an
    error). This is `run_ocr`'s per-file body, pulled out separately so
    `run_ocr_batch` can process files interleaved across sources rather than
    one whole source at a time, and so OCR inference - the actual work
    worth parallelizing - runs without `db_lock` held; every sqlite read/
    write around it is serialized through `db_lock` since a single
    connection isn't safe for unsynchronized concurrent use.
    """
    with db_lock:
        document_id, duplicate_of_id = _upsert_document(conn, source.id, file_path, file_type)
        conn.commit()

    if duplicate_of_id is not None:
        with db_lock:
            _mark_duplicate(conn, document_id, duplicate_of_id)
            conn.commit()
        return True

    process = psutil.Process()
    process.cpu_percent(interval=None)  # prime; the next call reports usage since now
    mem_before = process.memory_info().rss

    reader = _READERS[file_path.suffix.lower()]
    max_attempts = 1 + get_ocr_retry_attempts(conn)
    attempt = 0
    last_exc: Exception | None = None
    succeeded = False
    pages: list[PageResult] | None = None
    while attempt < max_attempts and not succeeded:
        attempt += 1
        try:
            pages = reader.ocr(conn, file_path)
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the batch
            last_exc = exc
        else:
            succeeded = True

    with db_lock:
        if succeeded:
            assert pages is not None
            if file_type == "pdf":
                conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
                conn.executemany(
                    "INSERT INTO pdf_pages "
                    "(document_id, page_number, ocr_text, confidence, source, "
                    "ocr_engine, language, image_width, image_height) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            document_id,
                            page_number,
                            page.text,
                            page.confidence,
                            page.source,
                            page.ocr_engine,
                            page.language,
                            page.image_width,
                            page.image_height,
                        )
                        for page_number, page in enumerate(pages, start=1)
                    ],
                )
            else:
                image_page = pages[0]
                conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_id,))
                conn.execute(
                    "INSERT INTO image_pages "
                    "(document_id, ocr_text, confidence, ocr_engine, language, "
                    "image_width, image_height) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        document_id,
                        image_page.text,
                        image_page.confidence,
                        image_page.ocr_engine,
                        image_page.language,
                        image_page.image_width,
                        image_page.image_height,
                    ),
                )

        peak_memory_mb = max(mem_before, process.memory_info().rss) / (1024 * 1024)
        cpu_percent = process.cpu_percent(interval=None)
        conn.execute(
            "UPDATE document_index SET retry_count = ?, peak_memory_mb = ?, cpu_percent = ? "
            "WHERE id = ?",
            (attempt - 1, peak_memory_mb, cpu_percent, document_id),
        )

        if not succeeded:
            _mark_error(conn, document_id, str(last_exc))
        else:
            _mark_indexed(conn, document_id)
            _update_processing_metrics(conn, document_id, file_type)
            _update_confidence_metrics(conn, document_id, file_type)

        conn.commit()

    return succeeded


_IDLE_POLL_SECONDS = 0.5


class _Wait:
    """Sentinel: this slot is idle - parked past the current active worker count."""


_WAIT = _Wait()


def _would_exceed_budget(conn: sqlite3.Connection, item: _PendingFile) -> bool:
    """Whether starting `item` right now would push CPU/memory past the busy thresholds.

    Projects live system usage (`psutil`, not just this run's own workers -
    other processes share the same headroom) forward by `item`'s historical
    footprint for its file_type + size bucket (`processing_metrics`). Missing
    file size or no history yet for that bucket both just skip the check -
    this only holds a file back when there's real evidence it would hurt,
    never on the strength of a guess. Caller already holds `db_lock`.
    """
    try:
        file_size_bytes = item.path.stat().st_size
    except OSError:
        return False

    row = conn.execute(
        "SELECT avg_peak_memory_mb, avg_cpu_percent FROM processing_metrics "
        "WHERE file_type = ? AND size_bucket = ?",
        (item.file_type, _size_bucket(file_size_bytes)),
    ).fetchone()
    if row is None:
        return False

    memory = psutil.virtual_memory()
    projected_memory_percent = memory.percent + (
        row["avg_peak_memory_mb"] / (memory.total / (1024 * 1024)) * 100
    )
    # interval=None (non-blocking, delta since the last call) rather than the
    # brief blocking sample `_auto_worker_count` takes once per run - this is
    # checked on every dequeue attempt, far too often to afford a sleep each time.
    projected_cpu_percent = psutil.cpu_percent(interval=None) + row["avg_cpu_percent"]
    return (
        projected_memory_percent >= _MEMORY_BUSY_THRESHOLD
        or projected_cpu_percent >= _CPU_BUSY_THRESHOLD
    )


def _run_auto_elastic(
    conn: sqlite3.Connection,
    pending: list[_PendingFile],
    initial_workers: int,
    handle_one: Callable[[_PendingFile], None],
    should_stop: Callable[[], bool] | None,
    on_workers_changed: Callable[[int], None] | None,
    *,
    db_lock: threading.Lock,
) -> None:
    """Process `pending` with a worker count re-resolved after every file.

    Spawns up to `min(THREAD_WORKERS_MAX, len(pending))` worker threads up
    front - an idle one just waits (cheap), never torn down or recreated -
    but only lets `active_workers` of them (by slot index) actually pull
    work at a time. `active_workers` is recomputed via
    `resolve_thread_workers` after every file finishes, from the file-type
    mix still remaining, so the active count grows or shrinks with current
    CPU/memory headroom as the run progresses rather than being fixed for
    the whole run.
    """
    max_slots = max(1, min(THREAD_WORKERS_MAX, len(pending)))
    remaining_counts = new_file_type_counts()
    for item in pending:
        remaining_counts[item.file_type] += 1

    coord_lock = threading.Lock()
    next_index = 0
    in_flight = 0
    active_workers = max(1, min(initial_workers, max_slots))

    def take_next(slot: int) -> _PendingFile | _Wait | None:
        nonlocal next_index, in_flight
        with coord_lock:
            # Checked in this order deliberately: once the queue is drained,
            # every slot must be able to exit - including one parked past
            # `active_workers` - rather than waiting forever for a turn that
            # active_workers shrinking (as remaining work runs low) may
            # never actually give it.
            if next_index >= len(pending):
                return None
            if slot >= active_workers:
                return _WAIT
            item = pending[next_index]
            # Only defer for a heavier-than-usual file when something else is
            # already running - if this slot is the only thing left, nothing
            # will ever free up the budget it's waiting on, so it must proceed
            # regardless (queue order is otherwise preserved either way: the
            # head of the queue is never skipped, just held).
            if in_flight > 0:
                with db_lock:
                    if _would_exceed_budget(conn, item):
                        return _WAIT
            next_index += 1
            in_flight += 1
            return item

    def report_done(file_type: str) -> None:
        nonlocal active_workers, in_flight
        changed_to: int | None = None
        with coord_lock:
            in_flight -= 1
            remaining_counts[file_type] -= 1
            if sum(remaining_counts.values()) > 0:
                # `db_lock`, not just `coord_lock`: `resolve_thread_workers`
                # reads `conn` (the `thread_workers` setting), and every use
                # of this connection across worker threads is serialized
                # through `db_lock` - see `_process_file`.
                with db_lock:
                    resolved = resolve_thread_workers(conn, remaining_counts)
                new_active_workers = max(1, min(resolved, max_slots))
                if new_active_workers != active_workers:
                    active_workers = new_active_workers
                    changed_to = new_active_workers
        if changed_to is not None and on_workers_changed is not None:
            on_workers_changed(changed_to)

    def worker_loop(slot: int) -> None:
        while True:
            if should_stop is not None and should_stop():
                return
            item = take_next(slot)
            if item is None:
                return
            if isinstance(item, _Wait):
                time.sleep(_IDLE_POLL_SECONDS)
                continue
            handle_one(item)
            report_done(item.file_type)

    threads = [threading.Thread(target=worker_loop, args=(slot,)) for slot in range(max_slots)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def run_ocr_batch(
    conn: sqlite3.Connection,
    sources: list[Source],
    *,
    only_failed: bool = False,
    workers: int = 1,
    on_file_start: Callable[[str], None] | None = None,
    on_file_done: Callable[[str, bool], None] | None = None,
    on_workers_changed: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[str]:
    """Like `run_ocr`, but across every source in `sources` at once.

    Every source's pending files are flattened into a single list ordered
    by filename - `Path.name`, not the full path, and not grouped by source
    - before processing, so a run over multiple sources reads as them
    indexing in parallel rather than strictly one source at a time. This
    ordering is independent of `workers`, which separately controls how
    many files are actually OCR'd concurrently (see `resolve_thread_workers`
    for how that count is chosen; 0 or 1 processes the list sequentially in
    the calling thread with no pool at all).

    `only_failed` and the per-source `only_new_files` choice (a source
    that's already been indexed only has new/changed/failed files
    reconsidered; a fresh/reactivated source has every file reprocessed)
    match `run_ocr`'s semantics exactly, just applied per source before the
    combined list is built.

    `should_stop` is checked before each file is started; once it returns
    True, no further files are started - in-flight ones still finish - and
    the rest of the list is left untouched. `on_file_start`, when given, is
    called with a file's path right before it's (re)processed; `on_file_done`
    is called with its path and whether it succeeded immediately after -
    both from whichever thread actually processed that file.

    When the `thread_workers` setting is 'auto', the worker count is instead
    re-resolved after every file (see `_run_auto_elastic`) rather than fixed
    for the whole run at `workers` - so it keeps adapting to CPU/memory
    headroom and the shrinking pending mix as the run progresses; whenever
    that changes it, `on_workers_changed` (when given) is called with the
    new count, so a caller reporting progress can keep it current.

    A source's `sources.status` is only updated once at least one of its
    files in this run's list was attempted, using the outcome of whichever
    of its files got processed before the run stopped (if it did) - a
    source with no files attempted this run is left untouched.

    Returns the paths of the files actually (re)processed, in the order
    they finished (not the processing order for `workers` > 1).
    """
    pending: list[_PendingFile] = []
    for source in sources:
        only_new_files = source.status != "pending"
        if only_new_files and not only_failed:
            disk_files = list(_iter_supported_files(Path(source.path)))
            renamed_paths = _reconcile_renamed_and_removed_files(conn, source, disk_files)
            conn.commit()
            for renamed_path in sorted(renamed_paths):
                if on_file_done is not None:
                    on_file_done(renamed_path, True)
        for file_path, file_type in _iter_pending_files(
            conn, source, only_new_files=only_new_files, only_failed=only_failed
        ):
            pending.append(_PendingFile(source, file_path, file_type))

    pending.sort(key=lambda item: (item.path.name, str(item.path)))

    attempted_source_ids: set[int] = set()
    had_error_by_source: dict[int, bool] = {}
    processed_paths: list[str] = []
    state_lock = threading.Lock()
    db_lock = threading.Lock()

    def handle_one(item: _PendingFile) -> None:
        path_str = str(item.path)
        if on_file_start is not None:
            on_file_start(path_str)
        succeeded = _process_file(conn, item.source, item.path, item.file_type, db_lock=db_lock)
        with state_lock:
            processed_paths.append(path_str)
            attempted_source_ids.add(item.source.id)
            had_error_by_source[item.source.id] = (
                had_error_by_source.get(item.source.id, False) or not succeeded
            )
        if on_file_done is not None:
            on_file_done(path_str, succeeded)

    if get_thread_workers(conn) == THREAD_WORKERS_AUTO:
        _run_auto_elastic(
            conn, pending, workers, handle_one, should_stop, on_workers_changed, db_lock=db_lock
        )
    elif workers <= 1:
        for item in pending:
            if should_stop is not None and should_stop():
                break
            handle_one(item)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for item in pending:
                if should_stop is not None and should_stop():
                    break
                futures.append(executor.submit(handle_one, item))
            for future in futures:
                future.result()

    now = datetime.now(UTC).isoformat()
    for source in sources:
        if source.id in attempted_source_ids:
            conn.execute(
                "UPDATE sources SET status = ?, last_scanned_at = ? WHERE id = ?",
                ("error" if had_error_by_source[source.id] else "indexed", now, source.id),
            )
    conn.commit()

    return processed_paths
