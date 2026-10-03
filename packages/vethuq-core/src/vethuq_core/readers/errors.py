"""Errors raised when a file can't be read for a reason that retrying won't fix."""

from __future__ import annotations

from pathlib import Path


class UnreadableFileError(Exception):
    """A file couldn't be read for a reason that retrying won't fix.

    Subclasses give each cause a distinct, actionable message, which is what
    ends up in `document_index.error_message` - so a vanished file, a
    password-protected PDF, and a corrupted one are told apart rather than all
    landing as the same opaque failure.
    """


class FileRemovedError(UnreadableFileError):
    """The file disappeared (deleted, moved, or unmounted) while it was being indexed."""

    def __init__(self, file_path: Path) -> None:
        super().__init__(f"File removed during indexing: {file_path}")


class PasswordProtectedError(UnreadableFileError):
    """The file is encrypted and needs a password VethuQ doesn't have."""

    def __init__(self, file_path: Path) -> None:
        super().__init__(
            f"File is password-protected: {file_path} - remove the password "
            "protection and re-run indexing to include it"
        )


class CorruptedFileError(UnreadableFileError):
    """The file exists but can't be parsed - it's damaged or not a valid file of its type."""

    def __init__(self, file_path: Path, detail: str | None = None) -> None:
        message = f"File is corrupted or unreadable: {file_path}"
        super().__init__(f"{message} ({detail})" if detail else message)
