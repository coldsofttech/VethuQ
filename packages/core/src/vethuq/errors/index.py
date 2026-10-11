"""Errors raised when indexing."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class IndexingError(VethuQError):
    """Base class for indexing errors."""


class IndexAlreadyRunningError(IndexingError):
    """An index run is already going."""


class IndexRunNotFoundError(IndexingError):
    """There is no index run with that id."""


class CreditsError(VethuQError):
    """Base class for credit errors."""


class InvalidGrantError(CreditsError):
    """A credit grant or licence can't be redeemed."""


class CreditsExhaustedError(CreditsError):
    """There aren't enough credits for the work."""


class GitHubError(VethuQError):
    """Base class for GitHub runner errors."""


class GitHubAuthError(GitHubError):
    """The GitHub token is missing, rejected, or lacks a permission."""


class GitHubSetupError(GitHubError):
    """The runner repository couldn't be set up, updated or reached."""


class GitHubNotSetUpError(GitHubError):
    """No GitHub runner has been set up yet."""


class GitHubUnavailableError(GitHubError):
    """The GitHub tier isn't available: the policy has it off, or it needs a newer VethuQ."""


class TierError(VethuQError):
    """Base class for processing tier errors."""


class TierUnavailableError(TierError):
    """The processing tier asked for can't be used now (unknown, not installed, or not ready)."""
