"""Errors about the languages VethuQ reads documents in."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class LastLanguageError(VethuQError):
    """The language can't be disabled because it is the last one in use."""

    exit_code = 17


class LanguageUnavailableError(VethuQError):
    """An OCR language was asked for that isn't installed, enabled or known."""

    exit_code = 16