"""Internal error implementations; the public classes live in `vethuq.errors`."""

from __future__ import annotations

from vethuq._errors.generic import (
    _CorruptDatabaseError,
    _DataFolderNotWritableError,
    _InvalidConfigError,
    _LanguageUnavailableError,
    _LastLanguageError,
    _OcrModelMissingError,
    _SchemaVersionError,
    _StaleLockError,
    _StartupError,
    _VethuQError,
)
from vethuq._errors.logs import _InvalidLogRequestError, _LogError, _LogNotFoundError
from vethuq._errors.settings import _InvalidSettingValueError, _SettingsError
from vethuq._errors.sources import (
    _SourceAlreadyExistsError,
    _SourceError,
    _SourceNotFoundError,
    _SourceNotRemovedError,
    _SourceOverlapError,
    _SourcePathError,
)

__all__ = [
    "_CorruptDatabaseError",
    "_DataFolderNotWritableError",
    "_InvalidConfigError",
    "_InvalidLogRequestError",
    "_InvalidSettingValueError",
    "_LanguageUnavailableError",
    "_LastLanguageError",
    "_LogError",
    "_LogNotFoundError",
    "_OcrModelMissingError",
    "_SchemaVersionError",
    "_SettingsError",
    "_SourceAlreadyExistsError",
    "_SourceError",
    "_SourceNotFoundError",
    "_SourceNotRemovedError",
    "_SourceOverlapError",
    "_SourcePathError",
    "_StaleLockError",
    "_StartupError",
    "_VethuQError",
]
