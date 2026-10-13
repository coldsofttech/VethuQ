"""The kinds of file VethuQ can read: `VethuQ().file_types`.

File types come from add-ons; PDF (`vethuq-addon-pdf`), text (`vethuq-addon-txt`), CSV
(`vethuq-addon-csv`) and Markdown (`vethuq-addon-markdown`) are installed with VethuQ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vethuq._db import _Database
from vethuq._filetypes import _FileTypeCatalog, _FileTypes, _FileTypeView

__all__ = ["FileType", "FileTypes"]


@dataclass(frozen=True)
class FileType:
    """A kind of file VethuQ can read."""

    id: str  # for example "pdf"
    label: str  # "PDF"
    extensions: tuple[str, ...]  # lower-case with the dot: (".pdf",)
    available: bool  # can be used now
    reason: str  # why it can't, when it can't
    enabled: bool = True  # switched on (files of a switched-off type are skipped)

    @property
    def usable(self) -> bool:
        """Available and enabled: the file types whose files are actually read."""
        return self.available and self.enabled

    @classmethod
    def _from_view(cls, view: _FileTypeView) -> FileType:
        spec = view.spec
        return cls(
            id=spec.id,
            label=spec.label,
            extensions=tuple(spec.extensions),
            available=spec.available,
            reason="" if spec.available else spec.reason,
            enabled=view.enabled,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "extensions": list(self.extensions),
            "available": self.available,
            "enabled": self.enabled,
            "reason": self.reason,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class FileTypes:
    """The kinds of file VethuQ can read.

    Not created directly: use `VethuQ().file_types`.
    """

    def __init__(self, database: _Database, catalog: _FileTypeCatalog) -> None:
        self._database = database
        self._catalog = catalog

    def list_all(self) -> list[FileType]:
        """Every file type the installed add-ons provide, by id, with whether it is enabled."""
        with self._database.session() as session:
            views = _FileTypes.views(session, self._catalog.specs())
        return [FileType._from_view(view) for view in sorted(views, key=lambda v: v.id)]

    def list_enabled(self) -> list[FileType]:
        """The file types that are used: available and enabled."""
        return [file_type for file_type in self.list_all() if file_type.usable]

    def defaults(self) -> list[FileType]:
        """The file types installed with VethuQ (PDF, text, CSV and Markdown), by id: those
        whose add-on is still installed."""
        wanted = set(_FileTypes.DEFAULT_IDS)
        return [file_type for file_type in self.list_all() if file_type.id in wanted]

    def get(self, file_type_id: str) -> FileType:
        """One file type by id.

        Raises `FileTypeUnavailableError` if no installed add-on provides it (the hint lists the
        file types that are installed).
        """
        with self._database.session() as session:
            view = _FileTypes.find(session, self._catalog.specs(), file_type_id)
        return FileType._from_view(view)

    def enable(self, file_type_id: str) -> FileType:
        """Switch a file type back on and return it. It must be available.

        Raises `FileTypeUnavailableError` if it is unknown or not available.
        """
        with self._database.session() as session:
            view = _FileTypes.enable(session, self._catalog.specs(), file_type_id)
        return FileType._from_view(view)

    def disable(self, file_type_id: str) -> FileType:
        """Switch a file type off and return it: its files are no longer read when indexing.
        Files already indexed stay as they are.

        Raises `FileTypeUnavailableError` if it is unknown.
        """
        with self._database.session() as session:
            view = _FileTypes.disable(session, self._catalog.specs(), file_type_id)
        return FileType._from_view(view)
