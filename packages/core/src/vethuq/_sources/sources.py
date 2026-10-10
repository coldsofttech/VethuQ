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

from vethuq._db import _Source
from vethuq._errors import _SourceAlreadyExistsError, _SourcePathError


class _Sources:
    _logger = logging.getLogger("vethuq.database")

    @staticmethod
    def languages_value(languages: Sequence[str] | None) -> str | None:
        """The stored form of a language choice (`["en", "te"]` -> `"en,te"`); None for no choice.

        Ids are trimmed and lower-cased, and blanks and repeats dropped, keeping the order.
        """
        if languages is None:
            return None
        if isinstance(languages, str):
            raise TypeError('languages must be a list of language ids, e.g. ["en", "te"]')
        ids: list[str] = []
        for language in languages:
            value = str(language).strip().lower()
            if value and value not in ids:
                ids.append(value)
        return ",".join(ids) if ids else None

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
        is neither a file nor a folder, and `SourceAlreadyExistsError` if it is already an
        active source.
        """
        language_value = _Sources.languages_value(languages)
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
            if language_value is not None:
                existing.languages = language_value
            session.flush()
            _Sources._logger.info("Source reactivated: id=%d path=%s", existing.id, key)
            return existing

        source = _Source(
            path=key,
            source_type=source_type,
            status="pending",
            added_at=added_at,
            is_active=True,
            languages=language_value,
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
