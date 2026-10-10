"""What the update check found."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class UpdateStatus(StrEnum):
    DISABLED = "disabled"  # the setting or VETHUQ_UPDATE_CHECK turned the check off
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"  # a newer version exists
    BELOW_MINIMUM = "below_minimum"  # older than the minimum supported version
    UNKNOWN = "unknown"  # no usable policy, or a version that can't be compared


@dataclass(frozen=True)
class UpdateResult:
    status: UpdateStatus
    mode: str  # 'on', 'notify-only' or 'off' (what is in force)
    current: str
    distribution: str
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
        return self.notify and self.mode == "on" and self.status is not UpdateStatus.UNKNOWN

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
        """The result as plain data (for `--json` output)."""
        data = asdict(self)
        data["status"] = str(self.status)
        data["notify"] = self.notify
        data["message"] = self.message
        return data
