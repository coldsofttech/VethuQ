"""The kinds of file VethuQ can read: `VethuQ().file_types`.

File types come from add-ons; PDF (`vethuq-addon-pdf`), text (`vethuq-addon-txt`), CSV
(`vethuq-addon-csv`) and Markdown (`vethuq-addon-markdown`) are installed with VethuQ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vethuq._filetypes import _FileTypeCatalog
from vethuq_addon_api import FileTypeSpec

__all__ = ["FileType", "FileTypes"]


@dataclass(frozen=True)
class FileType:
    """A kind of file VethuQ can read."""

    id: str  # for example "pdf"
    label: str  # "PDF"
    extensions: tuple[str, ...]  # lower-case with the dot: (".pdf",)
    available: bool  # can be used now
    reason: str  # why it can't, when it can't

    @classmethod
    def _from_spec(cls, spec: FileTypeSpec) -> FileType:
        return cls(
            id=spec.id,
            label=spec.label,
            extensions=tuple(spec.extensions),
            available=spec.available,
            reason="" if spec.available else spec.reason,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "extensions": list(self.extensions),
            "available": self.available,
            "reason": self.reason,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class FileTypes:
    """The kinds of file VethuQ can read.

    Not created directly: use `VethuQ().file_types`.
    """

    def __init__(self, catalog: _FileTypeCatalog) -> None:
        self._catalog = catalog

    def list(self) -> list[FileType]:
        """Every file type the installed add-ons provide, by id."""
        return [FileType._from_spec(spec) for spec in self._catalog.specs()]

    def get(self, file_type_id: str) -> FileType | None:
        """One file type by id, or None if no installed add-on provides it."""
        wanted = str(file_type_id).strip().lower()
        return next((t for t in self.list() if t.id == wanted), None)
