"""The built-in policy used until one has been fetched, and when none can be used."""

from __future__ import annotations

from datetime import UTC, datetime

from vethuq._policy.model import DistributionVersions, Policy


class _Baseline:
    """Sequence 0, so any signed policy (sequence >= 1) supersedes it."""

    KID = "baseline"

    @staticmethod
    def policy() -> Policy:
        none = DistributionVersions(latest="0.0.0", minimum_supported="0.0.0")
        return Policy(
            schema_version=1,
            sequence=0,
            issued_at=datetime(1970, 1, 1, tzinfo=UTC),
            kid=_Baseline.KID,
            versions={"desktop": none, "pip": none},
        )
