"""Internal error implementations; the public classes live in `vethuq.errors`."""

from __future__ import annotations

from vethuq._errors.generic import (
    _CorruptDatabaseError,
    _DataFolderNotWritableError,
    _InvalidConfigError,
    _LanguageUnavailableError,
    _OcrModelMissingError,
    _SchemaVersionError,
    _StaleLockError,
    _StartupError,
    _VethuQError,
)
from vethuq._errors.sources import (
    _SourceAlreadyExistsError,
    _SourceError,
    _SourcePathError,
)

__all__ = [
    "_CorruptDatabaseError",
    "_DataFolderNotWritableError",
    "_InvalidConfigError",
    "_LanguageUnavailableError",
    "_OcrModelMissingError",
    "_SchemaVersionError",
    "_SourceAlreadyExistsError",
    "_SourceError",
    "_SourcePathError",
    "_StaleLockError",
    "_StartupError",
    "_VethuQError",
]
