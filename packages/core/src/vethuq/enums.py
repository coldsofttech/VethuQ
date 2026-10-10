"""The fixed sets of values used across VethuQ's public API."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "IntegrityCheckMode",
    "LogComponent",
    "LogLevel",
    "PolicySource",
    "PolicyStatus",
    "SortOrder",
    "SourceSortBy",
    "SourceStatus",
    "SourceType",
    "UpdateCheckMode",
    "UpdateStatus",
]


class SourceType(StrEnum):
    """What a source points at."""

    FILE = "file"
    FOLDER = "folder"


class SourceStatus(StrEnum):
    """Where a source is in its life."""

    PENDING = "pending"
    INDEXED = "indexed"
    ERROR = "error"
    REMOVED = "removed"


class SortOrder(StrEnum):
    """The direction of a sort."""

    ASC = "asc"
    DESC = "desc"


class SourceSortBy(StrEnum):
    """The fields sources can be sorted by."""

    ID = "id"
    PATH = "path"
    STATUS = "status"
    SOURCE_TYPE = "source_type"
    ADDED_AT = "added_at"
    LAST_SCANNED_AT = "last_scanned_at"


class LogComponent(StrEnum):
    """The parts of VethuQ that keep a log."""

    DATABASE = "database"
    INDEX = "index"
    UI = "ui"
    CLI = "cli"
    POLICY = "policy"


class LogLevel(StrEnum):
    """How much a log records, least to most severe."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PolicySource(StrEnum):
    """Where a policy came from."""

    FETCHED = "fetched"  # accepted by this call
    CACHE = "cache"  # the last accepted policy, checked again from disk
    BASELINE = "baseline"  # the built-in policy


class PolicyStatus(StrEnum):
    """What a policy check did."""

    CURRENT = "current"  # `current()`: nothing was fetched
    UPDATED = "updated"  # a newer policy was accepted
    UNCHANGED = "unchanged"  # the server has nothing newer
    SKIPPED = "skipped"  # checked recently, or no keys yet: no request made
    OFFLINE = "offline"  # every URL failed (network, timeout, size, HTTP error)
    REJECTED = "rejected"  # every URL answered but nothing was acceptable
    UPDATE_REQUIRED = "update_required"  # the policy needs a newer VethuQ than this one


class UpdateCheckMode(StrEnum):
    """What the update check does."""

    ON = "on"  # checks, and offers to update
    NOTIFY_ONLY = "notify-only"  # checks, and only tells you
    OFF = "off"  # never checks


class UpdateStatus(StrEnum):
    """What the update check found."""

    DISABLED = "disabled"  # the setting or VETHUQ_UPDATE_CHECK turned the check off
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"  # a newer version exists
    BELOW_MINIMUM = "below_minimum"  # older than the minimum supported version
    UNKNOWN = "unknown"  # no usable policy, or a version that can't be compared


class IntegrityCheckMode(StrEnum):
    """When the database's integrity check runs by itself."""

    AUTO = "auto"  # when the database is opened, at most once per interval
    ENABLE = "enable"  # every time the database is opened
    DISABLE = "disable"  # never by itself; `client.db.integrity_check()` still works
