"""Which policy distribution this program is: the desktop installer or the pip package."""

from __future__ import annotations

import sys
from importlib import resources
from importlib.resources.abc import Traversable


class Distribution:
    DESKTOP = "desktop"
    PIP = "pip"

    # `scripts/dev/release.py --desktop` writes the installer's version here before PyInstaller
    # runs, and the spec bundles it. The package versions inside the app (vethuq-core, ...) are
    # not the installer's version, so the frozen app can't read it from package metadata.
    STAMP_PACKAGE = "vethuq_core.updates"
    STAMP_FILENAME = "desktop_version.txt"

    @staticmethod
    def current() -> str:
        """`desktop` for the frozen installer build, `pip` for everything else."""
        return Distribution.DESKTOP if getattr(sys, "frozen", False) else Distribution.PIP

    @staticmethod
    def desktop_version(root: Traversable | None = None) -> str | None:
        """The installer version this build was stamped with, or None when there is no stamp."""
        try:
            folder = root if root is not None else resources.files(Distribution.STAMP_PACKAGE)
            text = (folder / Distribution.STAMP_FILENAME).read_text(encoding="utf-8").strip()
        except (OSError, ModuleNotFoundError):
            return None
        return text or None
