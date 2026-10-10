"""Rollback protection and key revocation (see vethuq-policy docs/envelope.md).

The highest accepted sequence is kept per signing key id. A key's floor is derived from the
keys still trusted, so a forged huge sequence from a compromised key can't block the standby
key's recovery policy, and stops counting once that key is revoked.
"""

from __future__ import annotations

from vethuq_core.policy.envelope import VerifiedEnvelope
from vethuq_core.policy.errors import RollbackError
from vethuq_core.policy.keys import PolicyKeys
from vethuq_core.policy.state import PolicyState


class SequenceRules:
    def __init__(self, keys: PolicyKeys) -> None:
        self._keys = keys

    def floor(self, kid: str, state: PolicyState) -> int:
        """The sequence a policy signed by `kid` must exceed."""
        if self._keys.is_standby(kid):
            return state.accepted.get(kid, 0)
        return max(
            (state.accepted.get(k, 0) for k in self._keys.kids if k not in state.revoked),
            default=0,
        )

    def check(self, verified: VerifiedEnvelope, state: PolicyState) -> None:
        """Raise `RollbackError` unless the sequence is above the floor for its key."""
        floor = self.floor(verified.kid, state)
        if verified.policy.sequence <= floor:
            raise RollbackError(
                f"sequence {verified.policy.sequence} is not above {floor} for key {verified.kid!r}"
            )

    def accept(self, verified: VerifiedEnvelope, state: PolicyState) -> PolicyState:
        """The state after applying a verified, rollback-checked policy."""
        updated = state.with_accepted(verified.kid, verified.policy.sequence)
        if verified.standby:
            # Only a standby-signed policy can revoke, never itself or another standby key.
            protected = self._keys.standby_kids | {verified.kid}
            updated = updated.with_revoked(
                [kid for kid in verified.policy.revoked_key_ids if kid not in protected]
            )
        return updated
