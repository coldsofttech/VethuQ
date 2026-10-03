"""File types: each lives in its own folder (reader plus a `type.json` manifest)."""

from __future__ import annotations

from vethuq_core.filetypes.filetype import FileType
from vethuq_core.filetypes.registry import FileTypes

__all__ = ["FileType", "FileTypes"]
