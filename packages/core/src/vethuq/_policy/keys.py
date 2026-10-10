"""The Ed25519 public keys and policy URLs compiled into the client."""

from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from vethuq._policy.errors import _PolicyFormatError


@dataclass(frozen=True)
class _PolicyKey:
    """One trusted public key. A standby key is the recovery path that can revoke other keys."""

    kid: str
    public_key: bytes
    standby: bool = False

    @staticmethod
    def from_b64url(kid: str, text: str, standby: bool = False) -> _PolicyKey:
        """Build a key from the contents of a `policy/keys/<kid>.pub` file (base64url)."""
        try:
            raw = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
        except (binascii.Error, ValueError) as exc:
            raise _PolicyFormatError(f"public key {kid!r} is not valid base64url") from exc
        if len(raw) != 32:
            raise _PolicyFormatError(f"public key {kid!r} must be 32 bytes, got {len(raw)}")
        return _PolicyKey(kid, raw, standby)


class _PolicyKeys:
    """A set of trusted keys, looked up by key id."""

    # Filled in once the production keys exist (coldsofttech/VethuQ-support#275): the current
    # policy key and the standby key, each as
    # `_PolicyKey.from_b64url(kid, "<policy/keys/kid.pub>")`.
    EMBEDDED: tuple[_PolicyKey, ...] = ()

    def __init__(self, keys: Iterable[_PolicyKey]) -> None:
        self._keys = {key.kid: key for key in keys}

    @staticmethod
    def embedded() -> _PolicyKeys:
        return _PolicyKeys(_PolicyKeys.EMBEDDED)

    @property
    def kids(self) -> tuple[str, ...]:
        return tuple(self._keys)

    @property
    def standby_kids(self) -> frozenset[str]:
        return frozenset(kid for kid, key in self._keys.items() if key.standby)

    def get(self, kid: str) -> _PolicyKey | None:
        return self._keys.get(kid)

    def is_standby(self, kid: str) -> bool:
        key = self._keys.get(kid)
        return key is not None and key.standby


class _PolicyUrls:
    """Where the signed policy is published, tried in order. Trust comes from the signature."""

    DEFAULT: tuple[str, ...] = (
        "https://coldsofttech.github.io/vethuq/policy/v1/policy.json",
        "https://cdn.jsdelivr.net/gh/coldsofttech/vethuq@main/policy/v1/policy.json",
        "https://raw.githubusercontent.com/coldsofttech/vethuq/main/policy/v1/policy.json",
    )
    ENV_VAR = "VETHUQ_POLICY_URLS"

    @staticmethod
    def resolve(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
        """The URLs to try, in order.

        `VETHUQ_POLICY_URLS` (comma- or whitespace-separated) replaces `DEFAULT` for staging,
        tests, or a company mirror. Only well-formed `https` URLs count; if none do, or the
        variable is unset or empty, `DEFAULT` is used. The signature, not the host, is what is
        trusted, so a wrong value can only make a fetch fail.
        """
        value = (environ if environ is not None else os.environ).get(_PolicyUrls.ENV_VAR, "")
        urls: list[str] = []
        for part in re.split(r"[,\s]+", value.strip()):
            parsed = urlparse(part)
            if parsed.scheme == "https" and parsed.netloc and part not in urls:
                urls.append(part)
        return tuple(urls) or _PolicyUrls.DEFAULT
