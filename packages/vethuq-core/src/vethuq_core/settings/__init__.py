"""VethuQ's persisted settings, grouped by area."""

from __future__ import annotations

from vethuq_core.settings.db import DbSettings
from vethuq_core.settings.gpu import GpuSettings
from vethuq_core.settings.index import IndexSettings
from vethuq_core.settings.ocr import OcrSettings
from vethuq_core.settings.search import SearchSettings
from vethuq_core.settings.settings import InvalidSettingValueError, Settings, SettingsError
from vethuq_core.settings.source import SourceSettings

__all__ = [
    "DbSettings",
    "GpuSettings",
    "IndexSettings",
    "InvalidSettingValueError",
    "OcrSettings",
    "SearchSettings",
    "Settings",
    "SettingsError",
    "SourceSettings",
]
