"""VethuQ core."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from vethuq._brand import _Brand

APP_NAME = _Brand.NAME
APP_TAGLINE = _Brand.TAGLINE

try:
    APP_VERSION = version("VethuQ")
except PackageNotFoundError:  # running from a source tree that isn't installed
    APP_VERSION = "0.1.0"

__version__ = APP_VERSION

__all__ = ["APP_NAME", "APP_TAGLINE", "APP_VERSION", "__version__"]
