"""PaddleOCR-backed `OcrEngine`. Only `vethuq_core.ocr.engines.registry` imports this."""

from __future__ import annotations

import os
from importlib.metadata import version as _package_version
from importlib.util import find_spec
from typing import TYPE_CHECKING

from vethuq_core.errors import OcrModelMissingError
from vethuq_core.logs import Logs
from vethuq_core.ocr.engines.base import OcrResult

# Must be set before `paddleocr` is imported: skips its startup check for
# connectivity to the model hoster, which is slow and unnecessary once models
# are already cached locally. cv2/paddle/paddleocr are all imported lazily
# inside the functions that use them (not here at module level) since they're
# heavy - importing this module shouldn't pull in Paddle/OCR init as a side
# effect.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

if TYPE_CHECKING:
    import numpy as np

_logger = Logs.get_logger("index")


class PaddleOcrEngine:
    """English-language PaddleOCR engine."""

    LANGUAGE = "en"

    NOT_INSTALLED_MESSAGE = "The OCR engine (PaddleOCR) isn't installed."
    NOT_INSTALLED_HINT = "Reinstall VethuQ to restore it."

    @staticmethod
    def check_installed() -> None:
        """Raise `OcrModelMissingError` if PaddleOCR can't be imported - a cheap check that
        doesn't load it, so a caller can fail fast before starting a background run."""
        if find_spec("paddleocr") is None:
            _logger.error("OCR engine is not installed")
            raise OcrModelMissingError(
                PaddleOcrEngine.NOT_INSTALLED_MESSAGE, PaddleOcrEngine.NOT_INSTALLED_HINT
            )

    def __init__(self, use_gpu: bool = False) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            _logger.error("OCR engine is not installed: %s", exc)
            raise OcrModelMissingError(
                PaddleOcrEngine.NOT_INSTALLED_MESSAGE, PaddleOcrEngine.NOT_INSTALLED_HINT
            ) from exc

        try:
            self._ocr = PaddleOCR(
                lang=PaddleOcrEngine.LANGUAGE,
                device=PaddleOcrEngine.resolve_device(use_gpu),
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
        except Exception as exc:
            _logger.exception("Could not load the OCR models")
            raise OcrModelMissingError(
                f"The OCR models couldn't be loaded ({exc}).",
                "Connect to the internet once so they can download, or reinstall VethuQ.",
            ) from exc
        self._name = f"paddleocr {_package_version('paddleocr')}"

    @staticmethod
    def resolve_device(use_gpu: bool) -> str:
        """Pick the inference device honoring the user's GPU setting.

        GPU is opt-in and disabled by default (see `vethuq_core.settings`). When
        enabled, it's only actually used if this is a CUDA-capable PaddlePaddle
        build with a visible GPU - otherwise we fall back to CPU rather than
        erroring out, since enabling the setting on a CPU-only install (the
        common case) shouldn't break OCR.
        """
        if not use_gpu:
            return "cpu"
        import paddle

        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu"
        _logger.warning(
            "GPU is enabled in settings, but no CUDA-capable PaddlePaddle build/GPU "
            "was found. Falling back to CPU."
        )
        return "cpu"

    @property
    def name(self) -> str:
        return self._name

    @property
    def language(self) -> str:
        return PaddleOcrEngine.LANGUAGE

    def recognize(self, image: str | np.ndarray) -> OcrResult:
        import cv2

        result = self._ocr.predict(image)
        page = result[0] if result else {}
        texts = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        confidence = sum(scores) / len(scores) if scores else 0.0

        array = cv2.imread(image) if isinstance(image, str) else image
        width = height = None
        if array is not None:
            height, width = array.shape[:2]
        return OcrResult(
            text="\n".join(texts),
            confidence=confidence,
            engine=self._name,
            language=PaddleOcrEngine.LANGUAGE,
            image_width=width,
            image_height=height,
            lines=tuple((text, float(score)) for text, score in zip(texts, scores, strict=False)),
        )
