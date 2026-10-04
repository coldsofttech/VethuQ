"""The OCR models on disk: what each language needs, what is downloaded, and managing them."""

from vethuq_core.ocr.models.store import (
    CleanResult,
    ClearResult,
    DownloadResult,
    ModelStatus,
    OcrModels,
)

__all__ = ["CleanResult", "ClearResult", "DownloadResult", "ModelStatus", "OcrModels"]
