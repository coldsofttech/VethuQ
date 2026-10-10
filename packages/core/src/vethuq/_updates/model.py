"""What the update check found."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from vethuq.enums import UpdateCheckMode, UpdateStatus


@dataclass(frozen=True)
class UpdateResult:
    """What the update check found, and whether to tell the user."""

    status: UpdateStatus
    mode: UpdateCheckMode  # what is in force: the setting, or off when the environment says so
    current: str  # the version running
    distribution: str  # which policy entry applies: "pip" or "desktop"
    latest: str | None = None
    minimum_supported: str | None = None
    release_notes_url: str | None = None
    snoozed: bool = False
    skipped: bool = False
    disabled_by_environment: bool = False
    policy_update_required: bool = False  # a newer policy exists that needs a newer VethuQ

    POLICY_MESSAGE = "Update VethuQ to receive new policy."

    @property
    def notify(self) -> bool:
        """Whether to tell the user now. A version below the minimum is never snoozed or skipped,
        because it only explains why some features are held back; local work is never blocked."""
        if self.status is UpdateStatus.DISABLED:
            return False
        if self.status is UpdateStatus.BELOW_MINIMUM:
            return True
        if self.snoozed:
            return False
        if self.status is UpdateStatus.AVAILABLE:
            return not self.skipped
        return self.policy_update_required

    @property
    def offer_install(self) -> bool:
        """Whether a front end that can install updates should offer to ('on', not notify-only)."""
        return self.notify and self.mode is UpdateCheckMode.ON and (
            self.status is not UpdateStatus.UNKNOWN
        )

    @property
    def message(self) -> str:
        """One line for the user; empty when there is nothing to say."""
        if self.status is UpdateStatus.BELOW_MINIMUM:
            return (
                f"VethuQ {self.current} is older than the minimum supported "
                f"{self.minimum_supported}; update to {self.latest}. Local features keep working; "
                "only features that need a newer version are held back."
            )
        if self.status is UpdateStatus.AVAILABLE:
            return f"VethuQ {self.latest} is available (you have {self.current})."
        if self.policy_update_required and self.status is not UpdateStatus.DISABLED:
            return self.POLICY_MESSAGE
        return ""

    def to_dict(self) -> dict[str, Any]:
        """The result as plain data (for JSON output)."""
        return {
            "status": self.status.value,
            "mode": self.mode.value,
            "current": self.current,
            "distribution": self.distribution,
            "latest": self.latest,
            "minimum_supported": self.minimum_supported,
            "release_notes_url": self.release_notes_url,
            "snoozed": self.snoozed,
            "skipped": self.skipped,
            "disabled_by_environment": self.disabled_by_environment,
            "policy_update_required": self.policy_update_required,
            "notify": self.notify,
            "message": self.message,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class FeatureAccess:
    """Whether a feature is available to this version of VethuQ, and why not when it isn't."""

    name: str
    allowed: bool
    message: str | None = None  # why it is unavailable (None when allowed)
    requires_update: bool = False  # unavailable only because this VethuQ is too old

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allowed": self.allowed,
            "message": self.message,
            "requires_update": self.requires_update,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
