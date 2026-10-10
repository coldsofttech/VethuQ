"""VethuQ core."""

from __future__ import annotations

from vethuq import addons, db, errors, logs, paths, policy, sources, updates
from vethuq._brand import _Brand
from vethuq._version import _Version
from vethuq.client import VethuQ
from vethuq.languages import Language
from vethuq.paths import Paths
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
    "addons",
    "db",
    "errors",
    "logs",
    "paths",
    "policy",
    "sources",
    "updates",
    "Language",
    "Paths",
    "VersionDetails",
    "VethuQ",
]
