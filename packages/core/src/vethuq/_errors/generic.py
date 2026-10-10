"""Internal implementations of the generic errors exposed in `vethuq.errors`.

Each internal class inherits from its public counterpart, so code that raises
`_InvalidConfigError` is caught by `except vethuq.errors.InvalidConfigError`.
"""

from __future__ import annotations

from vethuq import errors


class _VethuQError(errors.VethuQError):
    exit_code = 1

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} {self.hint}" if self.hint else self.message


class _StartupError(_VethuQError, errors.StartupError):
    pass


class _InvalidConfigError(_StartupError, errors.InvalidConfigError):
    exit_code = 10


class _DataFolderNotWritableError(_StartupError, errors.DataFolderNotWritableError):
    exit_code = 11


class _CorruptDatabaseError(_VethuQError, errors.CorruptDatabaseError):
    exit_code = 12


class _OcrModelMissingError(_VethuQError, errors.OcrModelMissingError):
    exit_code = 13


class _SchemaVersionError(_StartupError, errors.SchemaVersionError):
    exit_code = 14


class _StaleLockError(_StartupError, errors.StaleLockError):
    exit_code = 15


class _LanguageUnavailableError(_VethuQError, errors.LanguageUnavailableError):
    exit_code = 16
