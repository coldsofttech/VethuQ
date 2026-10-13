"""Errors about the file types VethuQ can read."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class FileTypeUnavailableError(VethuQError):
    """A file type was asked for that no installed add-on provides."""

    exit_code = 18
