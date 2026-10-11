"""The fixed sets of values used across VethuQ's public API."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "FileStatus",
    "AddonStatus",
    "CreditEntryKind",
    "ProcessingTier",
    "RemoteJobStatus",
    "CreditSortBy",
    "ConfidenceBand",
    "StatsGroupBy",
    "StatsSortBy",
    "IndexRunSortBy",
    "IndexRunStatus",
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
    """Where a source is overall, worked out from the state of its files."""

    PENDING = "pending"  # nothing has been processed yet
    IN_PROGRESS = "in_progress"  # some files are processed and others are still waiting
    COMPLETED = "completed"  # every file is processed
    ERROR = "error"  # everything is processed, but some files failed
    REMOVED = "removed"


class FileStatus(StrEnum):
    """Where one file of a source is in indexing."""

    PENDING = "pending"  # not processed yet
    PROCESSING = "processing"
    INDEXED = "indexed"
    ERROR = "error"
    MODIFIED = "modified"  # changed since it was indexed; it will be processed again
    REMOVED = "removed"  # no longer on disk (kept until the source is purged)
    UNSUPPORTED = "unsupported"  # VethuQ can't read this kind of file (yet)


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


class IndexRunStatus(StrEnum):
    """Where an index run is."""

    RUNNING = "running"
    COMPLETED = "completed"  # it ran to the end (some files may have failed: see its counts)
    STOPPED = "stopped"  # it was interrupted
    FAILED = "failed"  # it could not run, or its process died
    WAITING_CREDITS = "waiting_credits"  # it ran out of credits; run again after they reset
    WAITING_REMOTE = "waiting_remote"  # work was sent to a remote tier; collect the results later


class IndexRunSortBy(StrEnum):
    """What a list of index runs can be sorted by."""

    ID = "id"
    STARTED_AT = "started_at"
    COMPLETED_AT = "completed_at"
    STATUS = "status"
    FILES_TOTAL = "files_total"
    FILES_PROCESSED = "files_processed"
    FILES_FAILED = "files_failed"


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


class AddonStatus(StrEnum):
    """Whether an installed add-on is running."""

    LOADED = "loaded"
    INCOMPATIBLE = "incompatible"  # it needs a different add-on API version
    FAILED = "failed"  # it couldn't be loaded


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


class CreditEntryKind(StrEnum):
    """What a credit ledger entry records."""

    GRANT = "grant"  # credits received: the day's allowance, a starter, a licence
    CHARGE = "charge"  # credits spent on a page
    REFUND = "refund"  # credits given back for work that did not finish
    EXPIRE = "expire"  # credits that lapsed unspent


class CreditSortBy(StrEnum):
    """What a credit history can be sorted by."""

    AT = "at"
    AMOUNT = "amount_milli"
    KIND = "kind"


class ConfidenceBand(StrEnum):
    """How sure OCR was of a page's text (the cut-offs are in `settings.confidence`)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNRELIABLE = "unreliable"


class StatsGroupBy(StrEnum):
    """What `stats.overview` groups its rows by."""

    SOURCE = "source"
    LANGUAGE = "language"
    FILE_TYPE = "file_type"
    ENGINE = "engine"
    PAGE_SOURCE = "page_source"
    BAND = "band"
    DAY = "day"


class StatsSortBy(StrEnum):
    """What `stats.overview` rows can be sorted by."""

    KEY = "key"
    FILES = "files"
    PAGES = "pages"
    OCR_PAGES = "ocr_pages"
    CONFIDENCE = "confidence"
    DURATION = "duration_ms"
    CREDITS = "credits"
    FAILURES = "failures"


class ProcessingTier(StrEnum):
    """Where pages that need OCR are read. Add-ons can provide tiers with other ids."""

    LOCAL = "local"  # on this computer (always there)
    GITHUB = "github"  # in your own GitHub account (the GitHub add-on)
    HYBRID = "hybrid"  # local first, with some pages sent to GitHub


class RemoteJobStatus(StrEnum):
    """Where a batch of pages sent to a remote processing tier is."""

    SUBMITTED = "submitted"  # sent; the tier is working on it
    COMPLETED = "completed"  # its results were imported
    FAILED = "failed"  # the tier reported a failure; its pages and credits were given back
    EXPIRED = "expired"  # it took too long; its pages and credits were given back


class SearchSortBy(StrEnum):
    """What search results can be sorted by."""

    PATH = "path"  # file path, then page, then position (the default)
    SCORE = "score"  # best first, for engines that rank; matches without a score come last
    # Best match first, across engines: pages by how strict the strictest engine that found them
    # is, then by that engine's own signal; for `hybrid`, by reciprocal rank fusion. The default
    # for `hybrid`.
    RANK = "rank"
