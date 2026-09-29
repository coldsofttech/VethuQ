"""OCR engines behind a single interface - see `base.OcrEngine`."""

from vethuq_core.ocr.engines.base import OcrEngine, OcrResult
from vethuq_core.ocr.engines.registry import Engines

__all__ = ["Engines", "OcrEngine", "OcrResult"]
