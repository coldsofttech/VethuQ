"""Registering files and folders as sources: `VethuQ().sources.create(...)`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq._db import _Database, _Source
from vethuq._errors import _SourceAlreadyExistsError
from vethuq._sources import _Sources

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["Source", "Sources"]


@dataclass(frozen=True)
class Source:
    """A file or folder registered as a source.

    Describe a source with `path` and `languages`, pass it to `VethuQ().sources.create()`,
    and get back a `Source` with every field filled in. The fields below `languages` are
    set by VethuQ, so they are `None` until the source is created.
    """

    path: str
    # Language ids this source is read in, e.g. ["en", "te"]; None means the global setting.
    languages: list[str] | None = None
    id: int | None = None
    source_type: str | None = None  # "file" | "folder"
    status: str | None = None  # "pending" | "indexed" | "error" | "removed"
    added_at: str | None = None
    last_scanned_at: str | None = None
    is_active: bool | None = None
    removed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", str(self.path))
        if self.languages is not None:
            object.__setattr__(self, "languages", list(self.languages))

    @classmethod
    def _from_model(cls, model: _Source) -> Source:
        return cls(
            path=model.path,
            languages=model.language_codes or None,
            id=model.id,
            source_type=model.source_type,
            status=model.status,
            added_at=model.added_at,
            last_scanned_at=model.last_scanned_at,
            is_active=model.is_active,
            removed_at=model.removed_at,
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "path": self.path,
            "type": self.source_type,
            "status": self.status,
            "added_at": self.added_at,
            "last_scanned_at": self.last_scanned_at,
        }
        if self.languages:
            data["languages"] = list(self.languages)
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Sources:
    """Register and manage files and folders as OCR and indexing sources.

    Not created directly: use `VethuQ().sources`.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def create(
        self, source: Source | str | Path, *, languages: Sequence[str] | None = None
    ) -> Source:
        """Register a file or folder as a source and return its details.

        `source` is a path, or a `Source` describing one. `languages` lists the OCR
        languages the source is read in (`["en", "te"]`); left out, the global setting applies.
        Folders are indexed recursively. Re-creating a source that was removed reactivates it.

        Raises `SourcePathError` if the path does not exist or is neither a file nor a
        folder, `SourceAlreadyExistsError` if the path is already an active source or the
        `Source` given was already created, and `LanguageUnavailableError` if a language is
        not one VethuQ knows (the error lists the ones it does).
        """
        if isinstance(source, Source):
            if languages is not None:
                raise TypeError("Give languages on the Source, or as languages=..., not both.")
            if source.id is not None:
                raise _SourceAlreadyExistsError(
                    f"This source has already been created (id={source.id}).",
                    "Pass a new Source, or a path.",
                )
            path, languages = source.path, source.languages
        else:
            path = source
        with self._database.session() as session:
            return Source._from_model(_Sources.create(session, path, languages))
