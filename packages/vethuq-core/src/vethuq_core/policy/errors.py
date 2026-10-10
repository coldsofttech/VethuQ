"""Why a policy was refused. None of these stop VethuQ: the client keeps the last good policy."""

from __future__ import annotations


class PolicyError(Exception):
    """A fetched or cached policy can't be used."""


class PolicyFormatError(PolicyError):
    """The envelope or payload is malformed (bad JSON, base64url, missing or mistyped fields)."""


class UnknownKeyError(PolicyError):
    """The envelope names a key id this client doesn't embed."""


class RevokedKeyError(PolicyError):
    """The envelope is signed by a key id that has been revoked."""


class SignatureError(PolicyError):
    """The signature doesn't match the payload for the named key."""


class RollbackError(PolicyError):
    """The sequence isn't greater than the floor for its signing key (downgrade protection)."""


class SchemaTooNewError(PolicyError):
    """The payload's schema major is higher than this client supports."""
