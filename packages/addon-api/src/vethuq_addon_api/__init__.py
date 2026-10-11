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
from vethuq_addon_api.search import (
    Folded,
    Hit,
    Normalizer,
    NormalizerUse,
    PageText,
    Pipeline,
    SearchCorpus,
    SearchEngine,
    SearchEngineSpec,
    SearchQueryError,
    SearchRequest,
)
from vethuq_addon_api.tiers import JobState, OcrExecutor, OcrRequest, TierSpec

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
    "Folded",
    "FileTypeSpec",
    "Hit",
    "Hook",
    "Host",
    "JobState",
    "LanguageSpec",
    "Manifest",
    "MigrationInfo",
    "ModelProgress",
    "OcrEngine",
    "OcrEngineProvider",
    "Normalizer",
    "NormalizerUse",
    "OcrExecutor",
    "OcrModelSpec",
    "OcrPhaseSpec",
    "OcrRequest",
    "PageText",
    "Pipeline",
    "OcrResult",
    "PasswordProtectedError",
    "ReadPage",
    "Region",
    "SearchCorpus",
    "SearchEngine",
    "SearchEngineSpec",
    "SearchQueryError",
    "SearchRequest",
    "TierSpec",
    "UnreadableFileError",
    "extended_path",
]
