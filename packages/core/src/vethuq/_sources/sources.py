"""The source service: registering files and folders as VethuQ sources.

A "source" is a file or folder the user has told VethuQ to treat as input for OCR and
indexing. This module only manages the registration (the `sources` table); the scanning,
OCR and indexing pipeline consumes it separately.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vethuq._db import _Language, _Source, _SourceLanguage
from vethuq._errors import (
    _LanguageUnavailableError,
    _SourceAlreadyExistsError,
    _SourcePathError,
)


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
    def resolve(path: str | Path) -> tuple[Path, str]:
        """The absolute path and its source type (`file` or `folder`).

        Raises `SourcePathError` if the path does not exist or is neither.
        """
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise _SourcePathError(
                f"Path does not exist: {resolved}", "Check the path and try again."
            )
        if resolved.is_dir():
            return resolved, "folder"
        if resolved.is_file():
            return resolved, "file"
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
            existing.status = "pending"
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
            status="pending",
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
