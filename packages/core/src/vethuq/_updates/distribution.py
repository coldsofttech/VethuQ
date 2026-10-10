"""Which policy distribution this program is: the desktop installer or the pip package."""

from __future__ import annotations

import sys


class _Distribution:
    DESKTOP = "desktop"
    PIP = "pip"

    @staticmethod
    def current() -> str:
        """`desktop` for a frozen installer build, `pip` for everything else."""
        return _Distribution.DESKTOP if getattr(sys, "frozen", False) else _Distribution.PIP
