"""Version comparison: PEP 440 for the pip package, which also reads the policy's `x.y.z-rc.N`."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version


class Versions:
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
        left, right = Versions.parse(have), Versions.parse(wanted)
        return left is not None and right is not None and left < right

    @staticmethod
    def installed() -> str:
        """The VethuQ version this program is running ('unknown' when it can't be told)."""
        from vethuq_core.version import VersionInfo  # noqa: PLC0415 - heavy imports, only when asked

        return VersionInfo.vethuq_version()
