"""Internal implementations of the indexing errors exposed in `vethuq.errors`."""

from __future__ import annotations

from vethuq import errors
from vethuq._errors.generic import _VethuQError


class _IndexingError(_VethuQError, errors.IndexingError):
    exit_code = 50


class _IndexAlreadyRunningError(_IndexingError, errors.IndexAlreadyRunningError):
    exit_code = 51


class _IndexRunNotFoundError(_IndexingError, errors.IndexRunNotFoundError):
    exit_code = 52


class _CreditsError(_VethuQError, errors.CreditsError):
    exit_code = 60


class _InvalidGrantError(_CreditsError, errors.InvalidGrantError):
    exit_code = 61


class _CreditsExhaustedError(_CreditsError, errors.CreditsExhaustedError):
    exit_code = 62


class _GitHubError(_VethuQError, errors.GitHubError):
    exit_code = 70


class _GitHubAuthError(_GitHubError, errors.GitHubAuthError):
    exit_code = 71


class _GitHubSetupError(_GitHubError, errors.GitHubSetupError):
    exit_code = 72


class _GitHubNotSetUpError(_GitHubError, errors.GitHubNotSetUpError):
    exit_code = 73


class _GitHubUnavailableError(_GitHubError, errors.GitHubUnavailableError):
    exit_code = 74
