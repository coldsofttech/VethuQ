"""Internal error implementations; the public classes live in `vethuq.errors`."""

from __future__ import annotations

from vethuq._errors.errors import (
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

__all__ = [
    "_CorruptDatabaseError",
    "_DataFolderNotWritableError",
    "_InvalidConfigError",
    "_LanguageUnavailableError",
    "_OcrModelMissingError",
    "_SchemaVersionError",
    "_StaleLockError",
    "_StartupError",
    "_VethuQError",
]
