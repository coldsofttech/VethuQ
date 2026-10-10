"""The parsed policy: what the client reads from a verified payload.

Unknown fields are ignored. The whole verified payload is kept in `Policy.raw` so later
features (credit rates, limits, promotions) can read their sections without a client change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from vethuq_core.policy.errors import PolicyFormatError


class VersionNumber:
    """Just enough semver to compare `x.y.z` versions (pre-release and build parts ignored)."""

    _PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

    @staticmethod
    def parse(text: str) -> tuple[int, int, int] | None:
        match = VersionNumber._PATTERN.match(text.strip())
        if match is None:
            return None
        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch)


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
    """A remote feature flag; `min_client` limits it to clients at or above that version."""

    enabled: bool
    min_client: str | None = None


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
    raw: Mapping[str, Any] = field(default_factory=dict)

    def active_notices(self, now: datetime | None = None) -> tuple[Notice, ...]:
        moment = now or datetime.now(UTC)
        return tuple(notice for notice in self.notices if notice.is_active(moment))

    def is_enabled(self, name: str, default: bool, client_version: str | None = None) -> bool:
        """The flag's value for this client, or `default` when the policy doesn't cover it."""
        feature = self.features.get(name)
        if feature is None:
            return default
        if feature.min_client is not None and client_version is not None:
            wanted, have = (
                VersionNumber.parse(feature.min_client),
                VersionNumber.parse(client_version),
            )
            if wanted is not None and have is not None and have < wanted:
                return default
        return feature.enabled

    @staticmethod
    def parse_time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise PolicyFormatError("a date-time is not a string")
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise PolicyFormatError(f"invalid date-time {value!r}") from exc
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    @staticmethod
    def from_payload(payload: Mapping[str, Any]) -> Policy:
        """Build a policy from an already verified payload. Raises `PolicyFormatError`."""
        schema_version, sequence = payload.get("schema_version"), payload.get("sequence")
        kid = payload.get("kid")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise PolicyFormatError("schema_version and sequence must be integers (sequence >= 1)")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise PolicyFormatError("schema_version and sequence must be integers (sequence >= 1)")
        if not isinstance(kid, str) or not kid:
            raise PolicyFormatError("kid must be a non-empty string")
        return Policy(
            schema_version=schema_version,
            sequence=sequence,
            issued_at=Policy.parse_time(payload.get("issued_at")),
            kid=kid,
            versions=Policy._parse_versions(payload.get("versions")),
            notices=Policy._parse_notices(payload.get("notices")),
            features=Policy._parse_features(payload.get("features")),
            revoked_key_ids=Policy._parse_revoked(payload.get("revoked_key_ids")),
            raw=dict(payload),
        )

    @staticmethod
    def _parse_versions(value: Any) -> dict[str, DistributionVersions]:
        if not isinstance(value, dict):
            raise PolicyFormatError("versions must be an object")
        versions: dict[str, DistributionVersions] = {}
        for name, entry in value.items():
            if not isinstance(entry, dict):
                continue
            latest, minimum = entry.get("latest"), entry.get("minimum_supported")
            if not isinstance(latest, str) or not isinstance(minimum, str):
                raise PolicyFormatError(f"versions.{name} needs latest and minimum_supported")
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
            except PolicyFormatError:
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
                min_client = entry.get("min_client")
                features[name] = Feature(
                    entry["enabled"], min_client if isinstance(min_client, str) else None
                )
        return features

    @staticmethod
    def _parse_revoked(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(dict.fromkeys(item for item in value if isinstance(item, str)))
