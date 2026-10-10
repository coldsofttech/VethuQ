"""Version comparison: PEP 440, which also reads the policy's `x.y.z-rc.N` spelling."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

from vethuq._updates.distribution import _Distribution
from vethuq._version import _Version


class _Versions:
    @staticmethod
    def parse(text: str | None) -> Version | None:
        """The version, or None when `text` is missing or not a version (e.g. 'unknown')."""
        if not text:
            return None
        try:
            return Version(text.strip())
        except InvalidVersion:
            return None

    @staticmethod
    def is_older(have: str | None, wanted: str | None) -> bool:
        """Whether `have` is older than `wanted`. False when either can't be parsed."""
        left, right = _Versions.parse(have), _Versions.parse(wanted)
        return left is not None and right is not None and left < right

    @staticmethod
    def installed() -> str:
        """This distribution's version as the policy names it ('unknown' if it can't be told)."""
        if _Distribution.current() == _Distribution.DESKTOP:
            return "unknown"  # the desktop app stamps its installer version here once it exists
        return _Version.app_version()
