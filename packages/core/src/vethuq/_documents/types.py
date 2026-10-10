"""Which files VethuQ can read."""

from __future__ import annotations

from pathlib import Path


class _FileTypes:
    # Only PDF is supported for now; more arrive with the readers that handle them.
    SUPPORTED_EXTENSIONS = frozenset({".pdf"})

    @staticmethod
    def extension(path: str | Path) -> str:
        return Path(path).suffix.lower()

    @staticmethod
    def is_supported(path: str | Path) -> bool:
        return _FileTypes.extension(path) in _FileTypes.SUPPORTED_EXTENSIONS
