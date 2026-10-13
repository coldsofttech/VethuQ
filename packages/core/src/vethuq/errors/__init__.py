"""Errors VethuQ raises on purpose.

Every error carries a plain-language `message` (what is wrong), a `hint` (what to do about
it) and a distinct `exit_code`. Catch `VethuQError` for any of them, or a more specific
class for one failure.
"""

from __future__ import annotations

from vethuq.errors.file_types import FileTypeUnavailableError
from vethuq.errors.generic import (
    CorruptDatabaseError,
    DataFolderNotWritableError,
    InvalidConfigError,
    OcrModelMissingError,
    SchemaVersionError,
    StaleLockError,
    StartupError,
    VethuQError,
)
from vethuq.errors.index import (
    CreditsError,
    CreditsExhaustedError,
    DatabaseIntegrityError,
    FileNotTrackedError,
    IndexAlreadyRunningError,
    IndexingError,
    IndexJobNotFoundError,
    IndexJobStateError,
    IndexNotRunningError,
    IndexRunNotFoundError,
    InvalidGrantError,
    SearchError,
    SearchOptionError,
    SearchQueryError,
    SearchUnavailableError,
)
from vethuq.errors.language import LanguageUnavailableError, LastLanguageError
from vethuq.errors.language import LanguageUnavailableError, LastLanguageError
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

from vethuq.errors.tier import TierError, TierNotFoundError, TierUnavailableError
__all__ = [
    "CorruptDatabaseError",
    "CreditsError",
    "TierError",
    "TierNotFoundError",
    "TierUnavailableError",
    "CreditsExhaustedError",
    "InvalidGrantError",
    "DataFolderNotWritableError",
    "DatabaseIntegrityError",
    "IndexJobNotFoundError",
    "IndexJobStateError",
    "FileNotTrackedError",
    "IndexAlreadyRunningError",
    "IndexNotRunningError",
    "IndexRunNotFoundError",
    "IndexingError",
    "FileTypeUnavailableError",
    "InvalidConfigError",
    "InvalidLogRequestError",
    "InvalidSettingValueError",
    "LanguageUnavailableError",
    "LastLanguageError",
    "LogError",
    "LogNotFoundError",
    "OcrModelMissingError",
    "SchemaVersionError",
    "SearchError",
    "SearchOptionError",
    "SearchQueryError",
    "SearchUnavailableError",
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
