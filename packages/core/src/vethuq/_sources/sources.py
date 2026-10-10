"""The source service: registering files and folders as VethuQ sources.

A "source" is a file or folder the user has told VethuQ to treat as input for OCR and
indexing. This module only manages the registration (the `sources` table); the scanning,
OCR and indexing pipeline consumes it separately.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vethuq._db import _Language, _Source, _SourceLanguage
from vethuq._errors import (
    _LanguageUnavailableError,
    _SourceAlreadyExistsError,
    _SourceNotFoundError,
    _SourceNotRemovedError,
    _SourcePathError,
)
from vethuq.enums import SortOrder, SourceSortBy, SourceStatus, SourceType

_E = TypeVar("_E", SourceStatus, SourceType, SortOrder, SourceSortBy)


class _Sources:
    _logger = logging.getLogger("vethuq.database")

    @staticmethod
    def clean_languages(languages: Sequence[str] | None) -> list[str] | None:
        """The language ids asked for, trimmed and lower-cased with blanks and repeats dropped;
        None for no choice."""
        if languages is None:
            return None
        if isinstance(languages, str):
            raise TypeError('languages must be a list of language ids, e.g. ["en", "te"]')
        ids: list[str] = []
        for language in languages:
            value = str(language).strip().lower()
            if value and value not in ids:
                ids.append(value)
        return ids or None

    @staticmethod
    def find_languages(session: Session, codes: list[str]) -> list[_Language]:
        """The `languages` rows for `codes`, in language order.

        Raises `LanguageUnavailableError` naming every id that is not a known language.
        """
        rows = list(
            session.scalars(
                select(_Language).where(_Language.language.in_(codes)).order_by(_Language.id)
            )
        )
        found = {row.language for row in rows}
        missing = [code for code in codes if code not in found]
        if missing:
            available = session.scalars(select(_Language.language).order_by(_Language.id)).all()
            names = ", ".join(f"'{code}'" for code in missing)
            noun = "language" if len(missing) == 1 else "languages"
            raise _LanguageUnavailableError(
                f"Unknown {noun} {names}.", f"Available languages: {', '.join(available)}."
            )
        return rows

    @staticmethod
    def resolve(path: str | Path) -> tuple[Path, SourceType]:
        """The absolute path and its source type.

        Raises `SourcePathError` if the path does not exist or is neither.
        """
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise _SourcePathError(
                f"Path does not exist: {resolved}", "Check the path and try again."
            )
        if resolved.is_dir():
            return resolved, SourceType.FOLDER
        if resolved.is_file():
            return resolved, SourceType.FILE
        raise _SourcePathError(
            f"Path is neither a file nor a folder: {resolved}", "Use a file or a folder."
        )

    @staticmethod
    def find_by_path(session: Session, path: str) -> _Source | None:
        return session.scalars(select(_Source).where(_Source.path == path)).first()

    @staticmethod
    def create(
        session: Session, path: str | Path, languages: Sequence[str] | None = None
    ) -> _Source:
        """Register a file or folder as a source. Folders are indexed recursively.

        Re-adding a path that was previously removed reactivates that source (reset to
        'pending') instead of failing. Raises `SourcePathError` if the path does not exist or
        is neither a file nor a folder, `SourceAlreadyExistsError` if it is already an active
        source, and `LanguageUnavailableError` if a language is not a known one.
        """
        codes = _Sources.clean_languages(languages)
        chosen = _Sources.find_languages(session, codes) if codes else None
        resolved, source_type = _Sources.resolve(path)
        key = str(resolved)
        added_at = datetime.now(UTC).isoformat()

        existing = _Sources.find_by_path(session, key)
        if existing is not None:
            if existing.is_active:
                raise _SourceAlreadyExistsError(
                    f"Path is already registered: {resolved}",
                    f"It is source {existing.id}.",
                )
            existing.source_type = source_type
            existing.status = SourceStatus.PENDING
            existing.added_at = added_at
            existing.last_scanned_at = None
            existing.is_active = True
            existing.removed_at = None
            if chosen is not None:
                existing.language_links = [_SourceLanguage(language=row) for row in chosen]
            session.flush()
            _Sources._logger.info("Source reactivated: id=%d path=%s", existing.id, key)
            return existing

        source = _Source(
            path=key,
            source_type=source_type,
            status=SourceStatus.PENDING,
            added_at=added_at,
            is_active=True,
            language_links=[_SourceLanguage(language=row) for row in chosen or []],
        )
        session.add(source)
        try:
            session.flush()
        except IntegrityError:
            # Another process registered the same path between the lookup and the insert.
            session.rollback()
            raise _SourceAlreadyExistsError(f"Path is already registered: {resolved}") from None
        _Sources._logger.info("Source created: id=%d path=%s", source.id, key)
        return source

    # ----- reading --------------------------------------------------------------------------

    @staticmethod
    def _matches(id_or_path: int | str | Path) -> ColumnElement[bool]:
        """The condition that picks a source by its id (an int) or its path (a str or Path)."""
        if isinstance(id_or_path, bool) or not isinstance(id_or_path, int | str | Path):
            raise TypeError("A source is identified by its id (int) or its path (str or Path).")
        if isinstance(id_or_path, int):
            return _Source.id == id_or_path
        return _Source.path == str(Path(id_or_path).expanduser().resolve())

    @staticmethod
    def get(
        session: Session, id_or_path: int | str | Path, *, include_removed: bool = False
    ) -> _Source:
        """The source with this id or path. Removed sources are found only with
        `include_removed`; otherwise, or if there is none, `SourceNotFoundError`."""
        statement = select(_Source).where(_Sources._matches(id_or_path))
        if not include_removed:
            statement = statement.where(_Source.is_active.is_(True))
        source = session.scalars(statement).first()
        if source is None:
            kind = "source" if include_removed else "active source"
            raise _SourceNotFoundError(
                f"No {kind} matches: {id_or_path}",
                "Use sources.list() to see the registered sources."
                if include_removed
                else "Use sources.list(include_removed=True) to include removed sources.",
            )
        return source

    @staticmethod
    def _coerce(enum_class: type[_E], value: _E | str, name: str) -> _E:
        try:
            return enum_class(value)
        except ValueError:
            options = ", ".join(member.value for member in enum_class)
            raise ValueError(f"{name} must be one of: {options} (not {value!r}).") from None

    @staticmethod
    def list_sources(
        session: Session,
        *,
        include_removed: bool = False,
        status: SourceStatus | str | None = None,
        source_type: SourceType | str | None = None,
        language: str | None = None,
        sort_by: SourceSortBy | str = SourceSortBy.ID,
        order: SortOrder | str = SortOrder.ASC,
    ) -> list[_Source]:
        """The registered sources, filtered and sorted.

        Removed sources are left out unless `include_removed`; asking for `status=removed`
        shows them whatever `include_removed` says. Ties in the sort are broken by id.
        """
        sort_by = _Sources._coerce(SourceSortBy, sort_by, "sort_by")
        order = _Sources._coerce(SortOrder, order, "order")
        statement = select(_Source)
        if status is not None:
            statement = statement.where(
                _Source.status == _Sources._coerce(SourceStatus, status, "status")
            )
        elif not include_removed:
            statement = statement.where(_Source.is_active.is_(True))
        if source_type is not None:
            statement = statement.where(
                _Source.source_type == _Sources._coerce(SourceType, source_type, "source_type")
            )
        if language is not None:
            codes = _Sources.clean_languages([language])
            if codes is None:
                raise ValueError("language must be a language id, e.g. 'en'.")
            (row,) = _Sources.find_languages(session, codes)
            statement = statement.where(
                _Source.language_links.any(_SourceLanguage.language_id == row.id)
            )
        column = getattr(_Source, sort_by.value)
        direction = column.desc() if order is SortOrder.DESC else column.asc()
        statement = statement.order_by(direction, _Source.id.asc())
        return list(session.scalars(statement))

    # ----- changing -------------------------------------------------------------------------

    @staticmethod
    def remove(session: Session, id_or_path: int | str | Path) -> _Source:
        """Soft-delete an active source: it is kept, marked removed, until it is purged."""
        source = _Sources.get(session, id_or_path)
        source.is_active = False
        source.status = SourceStatus.REMOVED
        source.removed_at = datetime.now(UTC).isoformat()
        session.flush()
        _Sources._logger.info("Source removed: id=%d path=%s", source.id, source.path)
        return source

    @staticmethod
    def set_languages(
        session: Session, id_or_path: int | str | Path, languages: Sequence[str] | None
    ) -> _Source:
        """Choose the languages an active source is read in; None or an empty list goes back
        to the global setting. Raises `LanguageUnavailableError` for an unknown language."""
        codes = _Sources.clean_languages(languages)
        chosen = _Sources.find_languages(session, codes) if codes else []
        source = _Sources.get(session, id_or_path)
        source.language_links = [_SourceLanguage(language=row) for row in chosen]
        session.flush()
        return source

    # ----- purging --------------------------------------------------------------------------

    @staticmethod
    def purge(session: Session, id_or_path: int | str | Path) -> _Source:
        """Permanently delete a source that has been removed, with its language choices.

        Raises `SourceNotFoundError` if nothing matches and `SourceNotRemovedError` if the
        source is still active.
        """
        source = _Sources.get(session, id_or_path, include_removed=True)
        if source.is_active:
            raise _SourceNotRemovedError(
                f"Source is still active: {source.path}", "Remove it before purging."
            )
        session.delete(source)
        session.flush()
        _Sources._logger.info("Source purged: id=%d path=%s", source.id, source.path)
        return source

    @staticmethod
    def purge_expired(session: Session, retention_minutes: int) -> list[_Source]:
        """Permanently delete the sources removed `retention_minutes` ago or longer."""
        if retention_minutes < 0:
            raise ValueError("retention_minutes can't be negative.")
        cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
        expired = list(
            session.scalars(
                select(_Source)
                .where(
                    _Source.status == SourceStatus.REMOVED,
                    _Source.removed_at.is_not(None),
                    _Source.removed_at <= cutoff,
                )
                .order_by(_Source.id)
            )
        )
        for source in expired:
            session.delete(source)
            _Sources._logger.info(
                "Cleanup (retention): purged source id=%d path=%s", source.id, source.path
            )
        session.flush()
        return expired
