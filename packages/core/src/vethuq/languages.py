"""The languages VethuQ can read documents in: `VethuQ().languages.list_all()`."""

from __future__ import annotations

import json
from dataclasses import dataclass

from vethuq._db import _Database, _Language
from vethuq._languages import _Languages

__all__ = ["Language", "Languages"]


@dataclass(frozen=True)
class Language:
    """A language VethuQ can read documents in."""

    id: int
    language: str  # the language id used when creating a source, e.g. "en"

    @classmethod
    def _from_model(cls, model: _Language) -> Language:
        return cls(id=model.id, language=model.language)

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "language": self.language}

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Languages:
    """The languages VethuQ can read documents in.

    Not created directly: use `VethuQ().languages`.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def list_all(self) -> list[Language]:
        """Every language VethuQ knows, in language order (English first)."""
        with self._database.session() as session:
            return [Language._from_model(row) for row in _Languages.list_all(session)]
