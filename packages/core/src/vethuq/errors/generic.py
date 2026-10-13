"""Errors VethuQ raises on purpose.

Each error carries a plain-language `message` (what is wrong), a `hint` (what to do about
it) and a distinct `exit_code`, so every front end can report it the same way and exit
non-zero. `str(error)` joins the message and hint.

Catch `VethuQError` for any of them, `StartupError` for the ones that stop VethuQ from
starting, or a specific subclass for one failure.
"""

from __future__ import annotations


class VethuQError(Exception):
    """Base class of every error VethuQ raises on purpose, with a hint on how to fix it."""

    message: str
    hint: str | None
    exit_code: int = 1

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} {self.hint}" if self.hint else self.message


class StartupError(VethuQError):
    """A failure that stops VethuQ from starting."""


class InvalidConfigError(StartupError):
    """The saved settings file or the `VETHUQ_HOME` setting can't be used."""

    exit_code = 10


class DataFolderNotWritableError(StartupError):
    """VethuQ can't create or write to its data folder."""

    exit_code = 11


class CorruptDatabaseError(VethuQError):
    """The database file is damaged or isn't a VethuQ database."""

    exit_code = 12


class OcrModelMissingError(VethuQError):
    """The OCR engine or its model files aren't available."""

    exit_code = 13


class SchemaVersionError(StartupError):
    """The database's schema is newer than this build of VethuQ supports."""

    exit_code = 14


class StaleLockError(StartupError):
    """A lock file exists but its process is no longer running."""

    exit_code = 15
