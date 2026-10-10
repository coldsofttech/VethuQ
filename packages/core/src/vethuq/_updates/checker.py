"""Compare this VethuQ with the signed policy's `latest` and `minimum_supported`."""

from __future__ import annotations

from dataclasses import replace

from vethuq._policy import Policy, PolicyResult
from vethuq._updates.model import FeatureAccess, UpdateResult
from vethuq._updates.versions import _Versions
from vethuq.enums import PolicySource, UpdateCheckMode, UpdateStatus


class _UpdateChecker:
    @staticmethod
    def disabled(current: str, distribution: str, by_environment: bool) -> UpdateResult:
        return UpdateResult(
            UpdateStatus.DISABLED,
            UpdateCheckMode.OFF,
            current,
            distribution,
            disabled_by_environment=by_environment,
        )

    @staticmethod
    def evaluate(
        policy_result: PolicyResult,
        mode: UpdateCheckMode,
        current: str,
        distribution: str,
        *,
        snoozed: bool = False,
        skipped_version: str | None = None,
    ) -> UpdateResult:
        """The pure comparison, with the user's snooze and skip applied."""
        unknown = UpdateResult(
            UpdateStatus.UNKNOWN,
            mode,
            current,
            distribution,
            snoozed=snoozed,
            policy_update_required=policy_result.update_required,
        )
        entry = policy_result.policy.versions.get(distribution)
        if entry is None or policy_result.source is PolicySource.BASELINE:
            return unknown
        if _Versions.parse(current) is None or _Versions.parse(entry.latest) is None:
            return unknown

        known = replace(
            unknown,
            latest=entry.latest,
            minimum_supported=entry.minimum_supported,
            release_notes_url=entry.release_notes_url,
        )
        if _Versions.is_older(current, entry.minimum_supported):
            return replace(known, status=UpdateStatus.BELOW_MINIMUM)
        if _Versions.is_older(current, entry.latest):
            return replace(
                known,
                status=UpdateStatus.AVAILABLE,
                skipped=skipped_version == entry.latest,
            )
        return replace(known, status=UpdateStatus.UP_TO_DATE)


class _FeatureGate:
    """Features that need a newer client are held back; everything local keeps working."""

    @staticmethod
    def check(
        name: str, default: bool, policy: Policy, client_version: str | None
    ) -> FeatureAccess:
        """Whether feature `name` is available to this client, and why not when it isn't.

        `default` is what the feature does when the policy doesn't cover it (the value built into
        this release). The policy can switch a feature off (kill switch), or turn it on for clients
        at or above `min_client`; an older client keeps `default` and is told it needs an update.
        """
        feature = policy.features.get(name)
        if feature is None:
            return FeatureAccess(name, default)
        wanted = feature.min_client
        if wanted is not None and _Versions.is_older(client_version, wanted):
            if feature.enabled and not default:
                message = (
                    feature.message or f"This feature needs VethuQ {feature.min_client} or newer."
                )
                return FeatureAccess(name, False, message, requires_update=True)
            return FeatureAccess(name, default)
        if not feature.enabled:
            return FeatureAccess(
                name, False, feature.message or "This feature is turned off for now."
            )
        return FeatureAccess(name, True)
