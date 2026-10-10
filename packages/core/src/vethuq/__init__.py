"""VethuQ core."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from vethuq import errors, paths
from vethuq._brand import _Brand
from vethuq.client import VethuQ
from vethuq.enums import SortOrder, SourceSortBy, SourceStatus, SourceType
from vethuq.languages import Language
from vethuq.paths import Paths
from vethuq.sources import PurgeResult, Source

APP_NAME = _Brand.NAME
APP_TAGLINE = _Brand.TAGLINE

try:
    APP_VERSION = version("VethuQ")
except PackageNotFoundError:  # running from a source tree that isn't installed
    APP_VERSION = "0.1.0"

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
    "SourceSortBy",
    "SourceStatus",
    "SourceType",
    "VethuQ",
]
