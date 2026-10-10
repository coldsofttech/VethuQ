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
    OcrModelMissingError,
    SchemaVersionError,
    StaleLockError,
    StartupError,
    VethuQError,
)
from vethuq.errors.settings import InvalidSettingValueError, SettingsError
from vethuq.errors.sources import (
    SourceAlreadyExistsError,
    SourceError,
    SourceNotFoundError,
    SourceNotRemovedError,
    SourcePathError,
)

__all__ = [
    "CorruptDatabaseError",
    "DataFolderNotWritableError",
    "InvalidConfigError",
    "InvalidSettingValueError",
    "LanguageUnavailableError",
    "OcrModelMissingError",
    "SchemaVersionError",
    "SettingsError",
    "SourceAlreadyExistsError",
    "SourceError",
    "SourceNotFoundError",
    "SourceNotRemovedError",
    "SourcePathError",
    "StaleLockError",
    "StartupError",
    "VethuQError",
]
