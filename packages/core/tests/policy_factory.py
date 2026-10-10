"""Builds signed policy envelopes with throwaway keys, for tests."""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vethuq._policy import _PolicyKey, _PolicyKeys


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class PolicySigner:
    """An ephemeral Ed25519 key that signs policies the way the admin tool does."""

    def __init__(self, kid: str = "test-1", standby: bool = False) -> None:
        self.kid = kid
        self.standby = standby
        self._private = Ed25519PrivateKey.generate()
        self.public = self._private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @property
    def key(self) -> _PolicyKey:
        return _PolicyKey(self.kid, self.public, self.standby)

    def keys(self, *others: PolicySigner) -> _PolicyKeys:
        return _PolicyKeys([self.key, *(other.key for other in others)])

    def payload(self, sequence: int = 1, **over: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": 1,
            "sequence": sequence,
            "issued_at": "2026-10-01T12:00:00Z",
            "kid": self.kid,
            "versions": {
                "desktop": {"latest": "2.0.0", "minimum_supported": "1.0.0"},
                "pip": {
                    "latest": "2.0.0",
                    "minimum_supported": "1.0.0",
                    "release_notes_url": "https://example.com/notes",
                },
            },
        }
        data.update(over)
        return data

    def envelope(self, payload: dict[str, Any] | bytes | None = None, **fields: Any) -> bytes:
        """The signed envelope file. `fields` override envelope fields (for broken envelopes)."""
        body = payload if payload is not None else self.payload()
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        envelope: dict[str, Any] = {
            "alg": "Ed25519",
            "kid": self.kid,
            "payload": b64url(raw),
            "sig": b64url(self._private.sign(raw)),
        }
        envelope.update(fields)
        return json.dumps(envelope).encode("utf-8")

    def signed(self, sequence: int = 1, **over: Any) -> bytes:
        return self.envelope(self.payload(sequence, **over))
