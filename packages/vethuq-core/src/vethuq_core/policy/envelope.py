"""Parse and verify the signed envelope (see vethuq-policy docs/envelope.md).

The payload is parsed only after its signature has been verified.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from vethuq_core.policy.errors import (
    PolicyFormatError,
    RevokedKeyError,
    SchemaTooNewError,
    SignatureError,
    UnknownKeyError,
)
from vethuq_core.policy.keys import PolicyKeys
from vethuq_core.policy.model import Policy


@dataclass(frozen=True)
class VerifiedEnvelope:
    """An envelope whose signature checked out, with its payload parsed."""

    kid: str
    standby: bool
    payload: bytes
    policy: Policy


class EnvelopeVerifier:
    ALGORITHM = "Ed25519"
    SIGNATURE_BYTES = 64
    SUPPORTED_SCHEMA = 1
    _BASE64URL = re.compile(r"^[A-Za-z0-9_-]*$")

    def __init__(self, keys: PolicyKeys, supported_schema: int = SUPPORTED_SCHEMA) -> None:
        self._keys = keys
        self._supported_schema = supported_schema

    @staticmethod
    def b64url_decode(text: Any) -> bytes:
        """Decode base64url without padding (RFC 4648 section 5)."""
        if not isinstance(text, str) or not EnvelopeVerifier._BASE64URL.match(text):
            raise PolicyFormatError("not base64url without padding")
        try:
            return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        except (binascii.Error, ValueError) as exc:
            raise PolicyFormatError("invalid base64url") from exc

    def verify(self, raw: bytes, revoked: Collection[str] = ()) -> VerifiedEnvelope:
        """Verify `raw` (the envelope file). Raises a `PolicyError` subclass on any problem."""
        try:
            envelope = json.loads(raw)
        except ValueError as exc:  # includes bad UTF-8
            raise PolicyFormatError("envelope is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise PolicyFormatError("envelope is not a JSON object")
        if envelope.get("alg") != self.ALGORITHM:
            raise PolicyFormatError(f"alg must be {self.ALGORITHM}")
        kid = envelope.get("kid")
        if not isinstance(kid, str) or not kid:
            raise PolicyFormatError("envelope kid is missing")

        key = self._keys.get(kid)
        if key is None:
            raise UnknownKeyError(f"unknown key id {kid!r}")
        if kid in revoked:
            raise RevokedKeyError(f"key id {kid!r} has been revoked")

        payload = self.b64url_decode(envelope.get("payload"))
        signature = self.b64url_decode(envelope.get("sig"))
        if len(signature) != self.SIGNATURE_BYTES:
            raise PolicyFormatError("signature must be 64 bytes")
        try:
            Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, payload)
        except InvalidSignature as exc:
            raise SignatureError(f"signature does not match key id {kid!r}") from exc

        return VerifiedEnvelope(kid, key.standby, payload, self._parse_payload(payload, kid))

    def _parse_payload(self, payload: bytes, kid: str) -> Policy:
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise PolicyFormatError("payload is not valid JSON") from exc
        if not isinstance(data, dict):
            raise PolicyFormatError("payload is not a JSON object")
        if data.get("kid") != kid:
            raise PolicyFormatError("payload kid does not match the envelope kid")
        schema = data.get("schema_version")
        if isinstance(schema, int) and not isinstance(schema, bool):
            if schema > self._supported_schema:
                raise SchemaTooNewError(f"schema version {schema} is newer than supported")
            if schema < 1:
                raise PolicyFormatError("schema_version must be at least 1")
        return Policy.from_payload(data)
