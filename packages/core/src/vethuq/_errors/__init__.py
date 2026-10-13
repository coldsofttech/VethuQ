"""Internal error implementations; the public classes live in `vethuq.errors`."""

from __future__ import annotations

from vethuq._errors.file_types import _FileTypeUnavailableError
from vethuq._errors.generic import (
    _CorruptDatabaseError,
    _DataFolderNotWritableError,
    _InvalidConfigError,
    _OcrModelMissingError,
    _SchemaVersionError,
    _StaleLockError,
    _StartupError,
    _VethuQError,
)
from vethuq._errors.index import (
    _CreditsError,
    _CreditsExhaustedError,
    _DatabaseIntegrityError,
    _FileNotTrackedError,
    _IndexAlreadyRunningError,
    _IndexingError,
    _IndexJobNotFoundError,
    _IndexJobStateError,
    _IndexNotRunningError,
    _IndexRunNotFoundError,
    _InvalidGrantError,
    _SearchError,
    _SearchOptionError,
    _SearchQueryError,
    _SearchUnavailableError,
)
from vethuq._errors.language import _LanguageUnavailableError, _LastLanguageError
from vethuq._errors.language import _LanguageUnavailableError, _LastLanguageError
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

from vethuq._errors.tier import _TierError, _TierNotFoundError, _TierUnavailableError
__all__ = [
    "_CorruptDatabaseError",
    "_TierError",
    "_TierNotFoundError",
    "_TierUnavailableError",
    "_CreditsError",
    "_CreditsExhaustedError",
    "_InvalidGrantError",
    "_DataFolderNotWritableError",
    "_DatabaseIntegrityError",
    "_IndexJobNotFoundError",
    "_IndexJobStateError",
    "_FileNotTrackedError",
    "_IndexAlreadyRunningError",
    "_IndexNotRunningError",
    "_IndexRunNotFoundError",
    "_IndexingError",
    "_FileTypeUnavailableError",
    "_InvalidConfigError",
    "_InvalidLogRequestError",
    "_InvalidSettingValueError",
    "_LanguageUnavailableError",
    "_LastLanguageError",
    "_LogError",
    "_LogNotFoundError",
    "_OcrModelMissingError",
    "_SchemaVersionError",
    "_SearchError",
    "_SearchOptionError",
    "_SearchQueryError",
    "_SearchUnavailableError",
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
