"""Why a policy was refused. None of these stop VethuQ: the client keeps the last good policy,
and they are never raised to the user (a refusal shows up as `PolicyResult.detail`)."""

from __future__ import annotations


class _PolicyError(Exception):
    """A fetched or cached policy can't be used."""


class _PolicyFormatError(_PolicyError):
    """The envelope or payload is malformed (bad JSON, base64url, missing or mistyped fields)."""


class _UnknownKeyError(_PolicyError):
    """The envelope names a key id this client doesn't embed."""


class _RevokedKeyError(_PolicyError):
    """The envelope is signed by a key id that has been revoked."""


class _SignatureError(_PolicyError):
    """The signature doesn't match the payload for the named key."""


class _RollbackError(_PolicyError):
    """The sequence isn't greater than the floor for its signing key (downgrade protection)."""


class _SchemaTooNewError(_PolicyError):
    """The payload's schema major is higher than this client supports."""
