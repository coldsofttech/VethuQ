"""Which policy distribution this program is: the desktop installer or the pip package."""

from __future__ import annotations

import sys


class Distribution:
    DESKTOP = "desktop"
    PIP = "pip"

    @staticmethod
    def current() -> str:
        """`desktop` for the frozen installer build, `pip` for everything else."""
        return Distribution.DESKTOP if getattr(sys, "frozen", False) else Distribution.PIP
