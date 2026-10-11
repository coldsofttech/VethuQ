"""Internal file-type catalog; the public view is `vethuq.file_types`."""

from __future__ import annotations

from vethuq._filetypes.catalog import _FileTypeCatalog
from vethuq._filetypes.details import _PageDetails

__all__ = ["_FileTypeCatalog", "_PageDetails"]
