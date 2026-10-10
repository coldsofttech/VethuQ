"""Errors add-ons raise."""

from __future__ import annotations


class AddonError(Exception):
    """Base class for add-on errors. `hint` says what the user can do about it."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} {self.hint}".strip()


class AddonLicenceError(AddonError):
    """The add-on has no valid licence."""
