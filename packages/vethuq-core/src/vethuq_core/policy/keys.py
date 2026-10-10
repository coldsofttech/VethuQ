"""The Ed25519 public keys and policy URLs compiled into the client."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable
from dataclasses import dataclass

from vethuq_core.policy.errors import PolicyFormatError


@dataclass(frozen=True)
class PolicyKey:
    """One trusted public key. A standby key is the recovery path that can revoke other keys."""

    kid: str
    public_key: bytes
    standby: bool = False

    @staticmethod
    def from_b64url(kid: str, text: str, standby: bool = False) -> PolicyKey:
        """Build a key from the contents of a `keys/<kid>.pub` file (base64url, no padding)."""
        try:
            raw = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
        except (binascii.Error, ValueError) as exc:
            raise PolicyFormatError(f"public key {kid!r} is not valid base64url") from exc
        if len(raw) != 32:
            raise PolicyFormatError(f"public key {kid!r} must be 32 bytes, got {len(raw)}")
        return PolicyKey(kid, raw, standby)


class PolicyKeys:
    """A set of trusted keys, looked up by key id."""

    # Filled in once the production keys exist (coldsofttech/VethuQ-support#275): the current
    # policy key and the standby key, each as `PolicyKey.from_b64url(kid, "<keys/kid.pub>")`.
    EMBEDDED: tuple[PolicyKey, ...] = ()

    def __init__(self, keys: Iterable[PolicyKey]) -> None:
        self._keys = {key.kid: key for key in keys}

    @staticmethod
    def embedded() -> PolicyKeys:
        return PolicyKeys(PolicyKeys.EMBEDDED)

    @property
    def kids(self) -> tuple[str, ...]:
        return tuple(self._keys)

    @property
    def standby_kids(self) -> frozenset[str]:
        return frozenset(kid for kid, key in self._keys.items() if key.standby)

    def get(self, kid: str) -> PolicyKey | None:
        return self._keys.get(kid)

    def is_standby(self, kid: str) -> bool:
        key = self._keys.get(kid)
        return key is not None and key.standby


class PolicyUrls:
    """Where the signed policy is published, tried in order. Trust comes from the signature."""

    DEFAULT: tuple[str, ...] = (
        "https://coldsofttech.github.io/vethuq-policy/v1/policy.json",
        "https://cdn.jsdelivr.net/gh/coldsofttech/vethuq-policy@main/v1/policy.json",
        "https://raw.githubusercontent.com/coldsofttech/vethuq-policy/main/v1/policy.json",
    )
