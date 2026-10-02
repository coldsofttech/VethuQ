"""PaddleOCR engine management: one lazily-built engine per thread."""

from __future__ import annotations

import os
import sqlite3
import threading
from importlib.metadata import version as _package_version
from typing import TYPE_CHECKING

# Must be set before `paddleocr` is imported: skips its startup check for
# connectivity to the model hoster, which is slow and unnecessary once models
# are already cached locally. cv2/numpy/paddle/pymupdf/paddleocr are all
# imported lazily inside the functions that use them (not here at module
# level) since they're heavy - importing this module shouldn't pull in
# Paddle/OCR init as a side effect.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

if TYPE_CHECKING:
    from paddleocr import PaddleOCR

from vethuq_core.logs import Logs
from vethuq_core.settings import GpuSettings

_logger = Logs.get_logger("index")


class Engine:
    LANGUAGE = "en"

    # PaddleOCR model init is expensive; share one English-language engine per
    # *thread* rather than per process - a run with N worker threads (see
    # `Scheduler.resolve_workers`) gets N engine instances so OCR inference itself
    # actually parallelizes, at the cost of N times the model memory footprint.
    # Constructed lazily so PDFs whose text is fully native never trigger it at all.
    _local = threading.local()

    @staticmethod
    def name() -> str:
        return f"paddleocr {_package_version('paddleocr')}"

    @staticmethod
    def resolve_device(conn: sqlite3.Connection) -> str:
        """Pick the inference device honoring the user's GPU setting.

        GPU is opt-in and disabled by default (see `vethuq_core.settings`). When
        enabled, it's only actually used if this is a CUDA-capable PaddlePaddle
        build with a visible GPU - otherwise we fall back to CPU rather than
        erroring out, since enabling the setting on a CPU-only install (the
        common case) shouldn't break OCR.
        """
        if not GpuSettings.is_enabled(conn):
            return "cpu"
        import paddle

        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu"
        _logger.warning(
            "GPU is enabled in settings, but no CUDA-capable PaddlePaddle build/GPU "
            "was found. Falling back to CPU."
        )
        return "cpu"

    @staticmethod
    def get(conn: sqlite3.Connection) -> PaddleOCR:
        engine = getattr(Engine._local, "engine", None)
        if engine is None:
            from paddleocr import PaddleOCR

            engine = PaddleOCR(
                lang=Engine.LANGUAGE,
                device=Engine.resolve_device(conn),
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
            Engine._local.engine = engine
        return engine
