"""Features that need a newer client are held back; everything local keeps working."""

from __future__ import annotations

from dataclasses import dataclass

from vethuq_core.policy import Policy, PolicyService
from vethuq_core.updates.versions import Versions


@dataclass(frozen=True)
class FeatureAccess:
    name: str
    allowed: bool
    message: str | None = None  # why it is unavailable (None when allowed)
    requires_update: bool = False  # unavailable only because this VethuQ is too old


class FeatureGate:
    @staticmethod
    def check(
        name: str,
        default: bool,
        policy: Policy | None = None,
        client_version: str | None = None,
    ) -> FeatureAccess:
        """Whether feature `name` is available to this client, and why not when it isn't.

        `default` is what the feature does when the policy doesn't cover it (the value built
        into this release). The policy can switch a feature off (kill switch), or turn it on for
        clients at or above `min_client`; an older client keeps `default` and is told it needs
        an update. Never raises and never touches the network.
        """
        try:
            current = policy or PolicyService.current().policy
            have = client_version if client_version is not None else Versions.installed()
            feature = current.features.get(name)
        except Exception:  # noqa: BLE001 - a policy problem must not stop local work
            return FeatureAccess(name, default)
        if feature is None:
            return FeatureAccess(name, default)

        if feature.min_client is not None and Versions.is_older(have, feature.min_client):
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
