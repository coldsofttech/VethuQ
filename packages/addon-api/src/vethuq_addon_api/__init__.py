"""The contract between VethuQ and its add-ons."""

from __future__ import annotations

from vethuq_addon_api.api import (
    API_VERSION,
    Addon,
    Hook,
    Host,
    LanguageSpec,
    Manifest,
    MigrationInfo,
    OcrPhaseSpec,
)
from vethuq_addon_api.errors import AddonError, AddonLicenceError
from vethuq_addon_api.ocr import (
    ModelProgress,
    OcrEngine,
    OcrEngineProvider,
    OcrModelSpec,
    OcrResult,
)
from vethuq_addon_api.readers import (
    CorruptedFileError,
    DocumentReader,
    FileRemovedError,
    FileTypeSpec,
    PasswordProtectedError,
    ReadPage,
    Region,
    UnreadableFileError,
    extended_path,
)

ENTRY_POINT_GROUP = "vethuq.addons"

__all__ = [
    "API_VERSION",
    "ENTRY_POINT_GROUP",
    "Addon",
    "AddonError",
    "AddonLicenceError",
    "CorruptedFileError",
    "DocumentReader",
    "FileRemovedError",
    "FileTypeSpec",
    "Hook",
    "Host",
    "LanguageSpec",
    "Manifest",
    "MigrationInfo",
    "ModelProgress",
    "OcrEngine",
    "OcrEngineProvider",
    "OcrModelSpec",
    "OcrPhaseSpec",
    "OcrResult",
    "PasswordProtectedError",
    "ReadPage",
    "Region",
    "UnreadableFileError",
    "extended_path",
]
