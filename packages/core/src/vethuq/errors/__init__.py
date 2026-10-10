"""Errors VethuQ raises on purpose.

Every error carries a plain-language `message` (what is wrong), a `hint` (what to do about
it) and a distinct `exit_code`. Catch `VethuQError` for any of them, or a more specific
class for one failure.
"""

from __future__ import annotations

from vethuq.errors.generic import (
    CorruptDatabaseError,
    DataFolderNotWritableError,
    InvalidConfigError,
    LanguageUnavailableError,
    LastLanguageError,
    OcrModelMissingError,
    SchemaVersionError,
    StaleLockError,
    StartupError,
    VethuQError,
)
from vethuq.errors.logs import InvalidLogRequestError, LogError, LogNotFoundError
from vethuq.errors.settings import InvalidSettingValueError, SettingsError
from vethuq.errors.sources import (
    SourceAlreadyExistsError,
    SourceError,
    SourceNotFoundError,
    SourceNotRemovedError,
    SourceOverlapError,
    SourcePathError,
)

__all__ = [
    "CorruptDatabaseError",
    "DataFolderNotWritableError",
    "InvalidConfigError",
    "InvalidLogRequestError",
    "InvalidSettingValueError",
    "LanguageUnavailableError",
    "LastLanguageError",
    "LogError",
    "LogNotFoundError",
    "OcrModelMissingError",
    "SchemaVersionError",
    "SettingsError",
    "SourceAlreadyExistsError",
    "SourceError",
    "SourceNotFoundError",
    "SourceNotRemovedError",
    "SourceOverlapError",
    "SourcePathError",
    "StaleLockError",
    "StartupError",
    "VethuQError",
]
