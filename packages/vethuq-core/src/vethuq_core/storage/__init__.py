"""VethuQ's storage-access layer: the `Storage` interface and its SQLite implementation."""

from __future__ import annotations

from pathlib import Path

from vethuq_core.db import Db, SchemaVersionError
from vethuq_core.storage.base import (
    DocumentStore,
    IndexRunStore,
    IntegrityStore,
    OcrStore,
    Row,
    SearchIndexRebuildError,
    SemanticStore,
    SettingsStore,
    SourceStore,
    StatsStore,
    Storage,
)
from vethuq_core.storage.sqlite import SqliteStorage


def default_db_path() -> Path:
    """Where the VethuQ database lives by default (the per-user `<data root>/db/` folder)."""
    return Db.default_db_path()


def schema_version() -> int:
    """The database schema version this build supports."""
    return Db.SCHEMA_VERSION


def open_storage(db_path: Path | None = None, *, check_same_thread: bool = True) -> Storage:
    """Open the VethuQ database (default location if `db_path` is None) as a `Storage`."""
    return SqliteStorage.open(db_path, check_same_thread=check_same_thread)


__all__ = [
    "DocumentStore",
    "IndexRunStore",
    "IntegrityStore",
    "OcrStore",
    "Row",
    "SchemaVersionError",
    "SearchIndexRebuildError",
    "SemanticStore",
    "SettingsStore",
    "SourceStore",
    "SqliteStorage",
    "StatsStore",
    "Storage",
    "default_db_path",
    "open_storage",
    "schema_version",
]
