"""Errors that stop VethuQ from starting or running.

Each error carries a plain-language `message` (what is wrong), a `hint` (what to do about
it) and a distinct `exit_code`, so every front end can report it the same way and exit
non-zero. `str(error)` joins the message and hint.

Catch `StartupError` for any of them, or a specific subclass for one failure.
"""

from __future__ import annotations


class StartupError(Exception):
    """A failure that stops VethuQ from starting or running, with a hint on how to fix it."""

    message: str
    hint: str | None
    exit_code: int


class InvalidConfigError(StartupError):
    """The saved settings file or the `VETHUQ_HOME` setting can't be used."""


class DataFolderNotWritableError(StartupError):
    """VethuQ can't create or write to its data folder."""


class CorruptDatabaseError(StartupError):
    """The database file is damaged or isn't a VethuQ database."""


class OcrModelMissingError(StartupError):
    """The OCR engine or its model files aren't available."""


class SchemaVersionError(StartupError):
    """The database's schema is newer than this build of VethuQ supports."""


class StaleLockError(StartupError):
    """A lock file exists but its process is no longer running."""


class LanguageUnavailableError(StartupError):
    """An OCR language was asked for that isn't installed, enabled or known."""
