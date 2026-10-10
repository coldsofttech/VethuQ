"""The parsed policy: what the client reads from a verified payload.

Unknown fields are ignored. The whole verified payload is kept in `Policy.raw` so later
features (credit rates, limits, promotions) can read their sections without a client change.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from vethuq._policy.errors import _PolicyFormatError
from vethuq.enums import PolicySource, PolicyStatus


@dataclass(frozen=True)
class DistributionVersions:
    """Latest and minimum supported version of one distribution (`desktop` or `pip`)."""

    latest: str
    minimum_supported: str
    release_notes_url: str | None = None


@dataclass(frozen=True)
class Notice:
    """A message to show, optionally limited to a time window."""

    id: str
    message: str
    severity: str = "info"
    link: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        if self.starts_at is not None and now < self.starts_at:
            return False
        return self.ends_at is None or now <= self.ends_at


@dataclass(frozen=True)
class Feature:
    """A remote feature flag; `min_client` limits it to clients at or above that version, and
    `message` explains the flag to the user when the feature is not available to them."""

    enabled: bool
    min_client: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class AddonPolicy:
    """What the policy says about one add-on. `enabled=False` is the remote kill switch."""

    enabled: bool = True
    latest: str | None = None
    minimum_supported: str | None = None
    min_client: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class Policy:
    schema_version: int
    sequence: int
    issued_at: datetime
    kid: str
    versions: Mapping[str, DistributionVersions]
    notices: tuple[Notice, ...] = ()
    features: Mapping[str, Feature] = field(default_factory=dict)
    revoked_key_ids: tuple[str, ...] = ()
    addons: Mapping[str, AddonPolicy] = field(default_factory=dict)
    revoked_licence_ids: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    def active_notices(self, now: datetime | None = None) -> tuple[Notice, ...]:
        """The notices whose time window includes `now` (the current time by default)."""
        moment = now or datetime.now(UTC)
        return tuple(notice for notice in self.notices if notice.is_active(moment))

    def to_dict(self) -> dict[str, Any]:
        """The verified payload exactly as signed, including sections this client doesn't use."""
        return dict(self.raw)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def parse_time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise _PolicyFormatError("a date-time is not a string")
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise _PolicyFormatError(f"invalid date-time {value!r}") from exc
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    @staticmethod
    def from_payload(payload: Mapping[str, Any]) -> Policy:
        """Build a policy from an already verified payload. Raises `_PolicyFormatError`."""
        schema_version, sequence = payload.get("schema_version"), payload.get("sequence")
        kid = payload.get("kid")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise _PolicyFormatError("schema_version and sequence must be integers")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise _PolicyFormatError("schema_version and sequence must be integers (sequence >= 1)")
        if not isinstance(kid, str) or not kid:
            raise _PolicyFormatError("kid must be a non-empty string")
        return Policy(
            schema_version=schema_version,
            sequence=sequence,
            issued_at=Policy.parse_time(payload.get("issued_at")),
            kid=kid,
            versions=Policy._parse_versions(payload.get("versions")),
            notices=Policy._parse_notices(payload.get("notices")),
            features=Policy._parse_features(payload.get("features")),
            revoked_key_ids=Policy._parse_revoked(payload.get("revoked_key_ids")),
            addons=Policy._parse_addons(payload.get("addons")),
            revoked_licence_ids=Policy._parse_revoked(payload.get("revoked_licence_ids")),
            raw=dict(payload),
        )

    @staticmethod
    def _parse_versions(value: Any) -> dict[str, DistributionVersions]:
        if not isinstance(value, dict):
            raise _PolicyFormatError("versions must be an object")
        versions: dict[str, DistributionVersions] = {}
        for name, entry in value.items():
            if not isinstance(entry, dict):
                continue
            latest, minimum = entry.get("latest"), entry.get("minimum_supported")
            if not isinstance(latest, str) or not isinstance(minimum, str):
                raise _PolicyFormatError(f"versions.{name} needs latest and minimum_supported")
            notes = entry.get("release_notes_url")
            versions[name] = DistributionVersions(
                latest, minimum, notes if isinstance(notes, str) else None
            )
        return versions

    @staticmethod
    def _parse_notices(value: Any) -> tuple[Notice, ...]:
        notices: list[Notice] = []
        for entry in value if isinstance(value, list) else []:
            # A malformed optional entry is skipped, not fatal: the rest of the policy stands.
            try:
                if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                    continue
                if not isinstance(entry.get("message"), str):
                    continue
                link = entry.get("link")
                notices.append(
                    Notice(
                        id=entry["id"],
                        message=entry["message"],
                        severity=str(entry.get("severity", "info")),
                        link=link if isinstance(link, str) else None,
                        starts_at=Policy._optional_time(entry.get("starts_at")),
                        ends_at=Policy._optional_time(entry.get("ends_at")),
                    )
                )
            except _PolicyFormatError:
                continue
        return tuple(notices)

    @staticmethod
    def _optional_time(value: Any) -> datetime | None:
        return None if value is None else Policy.parse_time(value)

    @staticmethod
    def _parse_features(value: Any) -> dict[str, Feature]:
        features: dict[str, Feature] = {}
        for name, entry in value.items() if isinstance(value, dict) else []:
            if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
                min_client, message = entry.get("min_client"), entry.get("message")
                features[name] = Feature(
                    entry["enabled"],
                    min_client if isinstance(min_client, str) else None,
                    message if isinstance(message, str) else None,
                )
        return features

    @staticmethod
    def _parse_addons(value: Any) -> dict[str, AddonPolicy]:
        addons: dict[str, AddonPolicy] = {}
        for name, entry in value.items() if isinstance(value, dict) else []:
            if not isinstance(entry, dict):
                continue

            def text(key: str, entry: dict[str, Any] = entry) -> str | None:
                item = entry.get(key)
                return item if isinstance(item, str) else None

            enabled = entry.get("enabled")
            addons[name] = AddonPolicy(
                enabled=enabled if isinstance(enabled, bool) else True,
                latest=text("latest"),
                minimum_supported=text("minimum_supported"),
                min_client=text("min_client"),
                message=text("message"),
            )
        return addons

    @staticmethod
    def _parse_revoked(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(dict.fromkeys(item for item in value if isinstance(item, str)))


@dataclass(frozen=True)
class PolicyResult:
    """What a policy call returned: the policy to use, where it came from, and what happened."""

    policy: Policy
    source: PolicySource
    status: PolicyStatus
    detail: str = ""  # why a fetch failed or was refused; the update message when update_required
    update_required: bool = False  # the latest policy needs a newer VethuQ than this one

    UPDATE_MESSAGE = "Update VethuQ to receive new policy."

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "status": self.status.value,
            "detail": self.detail,
            "update_required": self.update_required,
            "sequence": self.policy.sequence,
            "kid": self.policy.kid,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
