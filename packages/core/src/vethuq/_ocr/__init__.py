"""Internal OCR layer: engines, phases, models and reading pages; public view is `vethuq.ocr`."""

from __future__ import annotations

from vethuq._ocr.detection import _Assessment, _LanguageDetector, _Scripts
from vethuq._ocr.models import _ModelInfo, _Models
from vethuq._ocr.pages import _PageOcr, _PageResult, _QuickRead
from vethuq._ocr.runtime import _Ocr

__all__ = [
    "_Assessment",
    "_LanguageDetector",
    "_ModelInfo",
    "_Models",
    "_Ocr",
    "_PageOcr",
    "_PageResult",
    "_QuickRead",
    "_Scripts",
]
