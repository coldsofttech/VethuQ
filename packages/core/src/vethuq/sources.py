"""Registering and managing files and folders as sources: `VethuQ().sources`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq._db import _Database, _Source
from vethuq._errors import _SourceAlreadyExistsError
from vethuq._settings import _SourceSettings
from vethuq._sources import _FileEntry, _Files, _Sources
from vethuq.enums import SortOrder, SourceSortBy, SourceStatus, SourceType

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "PurgeResult",
    "SortOrder",
    "Source",
    "SourceFile",
    "SourceSortBy",
    "SourceStatus",
    "SourceType",
    "Sources",
]


@dataclass(frozen=True)
class Source:
    """A file or folder registered as a source.

    Describe a source with `path` and `languages`, pass it to `VethuQ().sources.create()`,
    and get back a `Source` with every field filled in. The fields below `languages` are
    set by VethuQ, so they are `None` until the source is created.
    """

    path: str
    # Language ids this source is read in, e.g. ["en"]; None means the global setting.
    languages: list[str] | None = None
    id: int | None = None
    source_type: SourceType | None = None
    status: SourceStatus | None = None
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
            "type": self.source_type.value if self.source_type else None,
            "status": self.status.value if self.status else None,
            "added_at": self.added_at,
            "last_scanned_at": self.last_scanned_at,
        }
        if self.languages:
            data["languages"] = list(self.languages)
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class PurgeResult:
    """A source that was permanently deleted."""

    id: int
    path: str
    source_type: SourceType

    @classmethod
    def _from_model(cls, model: _Source) -> PurgeResult:
        return cls(id=model.id, path=model.path, source_type=model.source_type)

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "path": self.path, "type": self.source_type.value}

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class SourceFile:
    """A file that belongs to a source."""

    path: str  # the absolute path
    relative_path: str  # relative to the source folder (just the name, for a file source)
    name: str
    size_bytes: int
    modified_at: str  # UTC, ISO 8601

    @classmethod
    def _from_entry(cls, entry: _FileEntry) -> SourceFile:
        return cls(
            path=entry.path,
            relative_path=entry.relative_path,
            name=entry.name,
            size_bytes=entry.size_bytes,
            modified_at=entry.modified_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "relative_path": self.relative_path,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Sources:
    """Register and manage files and folders as OCR and indexing sources.

    Not created directly: use `VethuQ().sources`. A source is identified by its id (an `int`)
    or its path (a `str` or `Path`).
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def create(
        self, source: Source | str | Path, *, languages: Sequence[str] | None = None
    ) -> Source:
        """Register a file or folder as a source and return its details.

        `source` is a path, or a `Source` describing one. `languages` lists the OCR
        languages the source is read in (`["en"]`); left out, the global setting applies.
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

    def get(self, id_or_path: int | str | Path, *, include_removed: bool = False) -> Source:
        """The source with this id or path.

        Removed sources are found only with `include_removed=True`. Raises
        `SourceNotFoundError` if there is no match.
        """
        with self._database.session() as session:
            return Source._from_model(
                _Sources.get(session, id_or_path, include_removed=include_removed)
            )

    def list(
        self,
        *,
        include_removed: bool = False,
        status: SourceStatus | str | None = None,
        source_type: SourceType | str | None = None,
        language: str | None = None,
        sort_by: SourceSortBy | str = SourceSortBy.ID,
        order: SortOrder | str = SortOrder.ASC,
    ) -> list[Source]:
        """The registered sources, filtered and sorted.

        Removed sources are left out unless `include_removed=True`; `status=SourceStatus.REMOVED`
        lists them whatever `include_removed` says. `language` keeps the sources read in that
        language. `sort_by` is a `SourceSortBy` and `order` a `SortOrder`; the default is by id,
        ascending. A `str` is accepted for any of the enums. Raises `ValueError` for a value
        that isn't one of them and `LanguageUnavailableError` for an unknown `language`.
        """
        with self._database.session() as session:
            return [
                Source._from_model(row)
                for row in _Sources.list_sources(
                    session,
                    include_removed=include_removed,
                    status=status,
                    source_type=source_type,
                    language=language,
                    sort_by=sort_by,
                    order=order,
                )
            ]

    def list_files(self, id_or_path: int | str | Path) -> list[SourceFile]:
        """The files that belong to an active source, as they are on disk now.

        For a folder, every file under it, however deep, sorted by path relative to the
        folder; for a file, that same file. Links to folders are not followed.

        Raises `SourceNotFoundError` if no active source matches and `SourcePathError` if
        the source's path is no longer on disk.
        """
        with self._database.session() as session:
            path = _Sources.get(session, id_or_path).path
        return [SourceFile._from_entry(entry) for entry in _Files.list(path)]

    def remove(self, id_or_path: int | str | Path) -> Source:
        """Remove an active source and return it, marked removed.

        It is kept, so it can be created again, until it is purged (see `purge` and
        `purge_expired`). Raises `SourceNotFoundError` if no active source matches.
        """
        with self._database.session() as session:
            return Source._from_model(_Sources.remove(session, id_or_path))

    def set_languages(
        self, id_or_path: int | str | Path, languages: Sequence[str] | None
    ) -> Source:
        """Set the languages an active source is read in and return it.

        `None` or an empty list goes back to the global setting. It applies to files indexed
        from now on. Raises `SourceNotFoundError` if no active source matches and
        `LanguageUnavailableError` for a language VethuQ doesn't know.
        """
        with self._database.session() as session:
            return Source._from_model(_Sources.set_languages(session, id_or_path, languages))

    def purge(self, id_or_path: int | str | Path) -> PurgeResult:
        """Permanently delete a removed source.

        Raises `SourceNotFoundError` if nothing matches and `SourceNotRemovedError` if the
        source is still active: remove it first.
        """
        with self._database.session() as session:
            return PurgeResult._from_model(_Sources.purge(session, id_or_path))

    def purge_expired(self, retention_minutes: int | None = None) -> list[PurgeResult]:
        """Permanently delete the sources that were removed long enough ago.

        `retention_minutes` is how long a removed source is kept; left out, the setting
        `settings.sources` applies (7 days unless changed). Returns what was deleted.
        """
        with self._database.session() as session:
            if retention_minutes is None:
                retention_minutes = _SourceSettings.get_removed_retention_minutes(session)
            return [
                PurgeResult._from_model(row)
                for row in _Sources.purge_expired(session, retention_minutes)
            ]
