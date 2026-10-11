"""The local tier: OCR on this computer, with the OCR engine an add-on provides."""

from __future__ import annotations

from vethuq._ocr import _Ocr
from vethuq_addon_api import OcrExecutor, OcrRequest, OcrResult


class _LocalExecutor(OcrExecutor):
    """Reads an image with this thread's engine for the request's language. Building an engine
    loads models, so `_Ocr` keeps one per thread and fetches missing models the first time."""

    def __init__(self, ocr: _Ocr) -> None:
        self._ocr = ocr

    def describe(self) -> str:
        return "this computer"

    def recognize(self, request: OcrRequest) -> OcrResult:
        engine, _phase = self._ocr.engine(request.language, request.phase)
        if request.angle:
            return engine.recognize(request.image, request.angle)
        return engine.recognize(request.image)
