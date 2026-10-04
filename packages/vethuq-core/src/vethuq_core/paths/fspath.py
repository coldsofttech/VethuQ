"""Filesystem path helpers: long Windows paths and keeping indexed files inside their source."""

from __future__ import annotations

import os
import sys
from pathlib import Path


class FsPath:
    # Windows' MAX_PATH is 260 including the terminating NUL; directories need room for an
    # 8.3 file name too, so the prefix is applied a little early.
    _LONG_PATH_THRESHOLD = 240
    _EXTENDED_PREFIX = "\\\\?\\"
    _EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"

    @staticmethod
    def extended(path: Path | str) -> Path:
        """`path` in a form the OS can open even past 260 characters.

        On Windows a long absolute path gets the extended-length (`\\\\?\\`) prefix; every
        other path (and every other platform) is returned unchanged. Use it for filesystem
        calls only - stored and displayed paths stay in their normal form.
        """
        text = str(path)
        if (
            sys.platform != "win32"
            or len(text) < FsPath._LONG_PATH_THRESHOLD
            or text.startswith(FsPath._EXTENDED_PREFIX)
        ):
            return Path(path)
        absolute = os.path.abspath(text)
        if absolute.startswith("\\\\"):
            return Path(FsPath._EXTENDED_UNC_PREFIX + absolute[2:])
        return Path(FsPath._EXTENDED_PREFIX + absolute)

    @staticmethod
    def plain(path: Path | str) -> Path:
        """`path` without any extended-length (`\\\\?\\`) prefix."""
        text = str(path)
        if text.startswith(FsPath._EXTENDED_UNC_PREFIX):
            return Path("\\\\" + text[len(FsPath._EXTENDED_UNC_PREFIX) :])
        if text.startswith(FsPath._EXTENDED_PREFIX):
            return Path(text[len(FsPath._EXTENDED_PREFIX) :])
        return Path(path)

    @staticmethod
    def is_within(path: Path | str, root: Path | str) -> bool:
        """Whether `path`, with symlinks/junctions/`..` resolved, is `root` or lies beneath it."""
        real_path = FsPath.plain(os.path.realpath(FsPath.extended(path)))
        real_root = FsPath.plain(os.path.realpath(FsPath.extended(root)))
        return real_path == real_root or real_root in real_path.parents
