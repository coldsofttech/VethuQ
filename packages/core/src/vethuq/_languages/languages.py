"""The language service: the languages VethuQ can read documents in."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vethuq._db import _Language


class _Languages:
    @staticmethod
    def list_all(session: Session) -> list[_Language]:
        """Every known language, in language order (English first)."""
        return list(session.scalars(select(_Language).order_by(_Language.id)))
