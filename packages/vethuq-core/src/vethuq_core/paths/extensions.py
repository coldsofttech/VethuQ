"""Normalized file extensions, the key per-extension statistics are tracked under."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


class Extensions:
    # Extensions that are the same format under another name.
    ALIASES = {"jpeg": "jpg"}

    @staticmethod
    def of(path: str | Path) -> str:
        """`path`'s extension, lowercase and without the dot, with aliases folded together.

        `Report.PDF` -> `pdf`, `scan.jpeg` -> `jpg`; '' for a file with no extension. Works on
        a stored path from any platform (either separator).
        """
        extension = PureWindowsPath(str(path)).suffix.lower().lstrip(".")
        return Extensions.ALIASES.get(extension, extension)
