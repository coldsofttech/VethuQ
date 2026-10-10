"""Internal database layer: models, schema and the connection."""

from __future__ import annotations

from vethuq._db.database import _Database
from vethuq._db.integrity import IntegrityCheckResult, _IntegrityCheck
from vethuq._db.migration import _Migration
from vethuq._db.models import (
    _Base,
    _Document,
    _DocumentIndex,
    _Language,
    _SchemaVersion,
    _Setting,
    _Source,
    _SourceLanguage,
)
from vethuq._db.schema import _Schema

__all__ = [
    "IntegrityCheckResult",
    "_Base",
    "_Database",
    "_Document",
    "_DocumentIndex",
    "_IntegrityCheck",
    "_Language",
    "_Migration",
    "_Schema",
    "_SchemaVersion",
    "_Setting",
    "_Source",
    "_SourceLanguage",
]
