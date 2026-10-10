"""What the client remembers between runs, written atomically.

    <data root>/policy/
        policy.json     the last accepted envelope, exactly as served
        state.json      per-key accepted sequences, revoked key ids, ETag and fetch times

Both are disposable: if either is missing or damaged the client behaves as if it has never
fetched (baseline policy, no downgrade memory beyond what is still readable).
"""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PolicyState:
    accepted: Mapping[str, int] = field(default_factory=dict)
    revoked: frozenset[str] = frozenset()
    etag: str | None = None
    etag_url: str | None = None
    last_check: float = 0.0
    last_failure: float = 0.0
    update_required: bool = False

    def with_accepted(self, kid: str, sequence: int) -> PolicyState:
        """Record `sequence` for `kid`; a key's own counter never goes down."""
        return replace(
            self, accepted={**self.accepted, kid: max(self.accepted.get(kid, 0), sequence)}
        )

    def with_revoked(self, kids: Collection[str]) -> PolicyState:
        """The revoked set only grows."""
        return replace(self, revoked=self.revoked | frozenset(kids))

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "accepted": dict(self.accepted),
            "revoked": sorted(self.revoked),
            "etag": self.etag,
            "etag_url": self.etag_url,
            "last_check": self.last_check,
            "last_failure": self.last_failure,
            "update_required": self.update_required,
        }

    @staticmethod
    def from_json(data: Any) -> PolicyState:
        """Read a saved state, dropping anything of the wrong type."""
        if not isinstance(data, dict):
            return PolicyState()
        accepted = data.get("accepted")
        revoked = data.get("revoked")
        etag, etag_url = data.get("etag"), data.get("etag_url")
        return PolicyState(
            accepted={
                k: v
                for k, v in (accepted.items() if isinstance(accepted, dict) else [])
                if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            },
            revoked=frozenset(
                k for k in (revoked if isinstance(revoked, list) else []) if isinstance(k, str)
            ),
            etag=etag if isinstance(etag, str) else None,
            etag_url=etag_url if isinstance(etag_url, str) else None,
            last_check=PolicyState._number(data.get("last_check")),
            last_failure=PolicyState._number(data.get("last_failure")),
            update_required=data.get("update_required") is True,
        )

    @staticmethod
    def _number(value: Any) -> float:
        return (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0
        )


class PolicyStore:
    """Reads and writes the cache folder. Reads never raise; writes raise `OSError`."""

    POLICY_FILENAME = "policy.json"
    STATE_FILENAME = "state.json"

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def read_envelope(self) -> bytes | None:
        try:
            return (self.directory / self.POLICY_FILENAME).read_bytes()
        except OSError:
            return None

    def read_state(self) -> PolicyState:
        try:
            return PolicyState.from_json(
                json.loads((self.directory / self.STATE_FILENAME).read_text(encoding="utf-8"))
            )
        except (OSError, ValueError):
            return PolicyState()

    def write_envelope(self, raw: bytes) -> None:
        self._write(self.POLICY_FILENAME, raw)

    def write_state(self, state: PolicyState) -> None:
        self._write(self.STATE_FILENAME, json.dumps(state.to_json()).encode("utf-8"))

    def _write(self, name: str, data: bytes) -> None:
        """Write to a temp file, flush it to disk, then swap it in so a crash can't tear it."""
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / name
        tmp = target.with_name(f"{name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
