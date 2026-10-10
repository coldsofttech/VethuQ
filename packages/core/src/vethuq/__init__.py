"""VethuQ core."""

from __future__ import annotations

from vethuq import errors, paths
from vethuq._brand import _Brand
from vethuq._version import _Version
from vethuq.client import VethuQ
from vethuq.enums import SortOrder, SourceSortBy, SourceStatus, SourceType
from vethuq.languages import Language
from vethuq.paths import Paths
from vethuq.sources import PurgeResult, Source, SourceFile
from vethuq.version import VersionDetails

APP_NAME = _Brand.NAME
APP_TAGLINE = _Brand.TAGLINE

APP_VERSION = _Version.app_version()

__version__ = APP_VERSION

__all__ = [
    "APP_NAME",
    "APP_TAGLINE",
    "APP_VERSION",
    "__version__",
    "errors",
    "paths",
    "Paths",
    "Language",
    "PurgeResult",
    "SortOrder",
    "Source",
    "SourceFile",
    "SourceSortBy",
    "SourceStatus",
    "SourceType",
    "VersionDetails",
    "VethuQ",
]
