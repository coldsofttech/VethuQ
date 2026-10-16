"""Values stored in the database that the public API doesn't expose."""

from __future__ import annotations

from enum import StrEnum


class _PageSource(StrEnum):
    """How a page's text was produced."""

    NATIVE = "native"  # straight from the file's text layer, no OCR
    OCR = "ocr"  # read from an image of the page
    MIXED = "mixed"  # the text layer, plus OCR of the images on the page


class _PassStatus(StrEnum):
    """Where a file's read in one language is."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


class _PassSource(StrEnum):
    """How a language came to be read."""

    DEFAULT = "default"  # the system default or the global setting
    AUTO = "auto"  # chosen by detection
    MANUAL = "manual"  # chosen for the source


class _GrantKind(StrEnum):
    """What kind of credits a grant holds, which sets the order they are spent in."""

    PROMO = "promo"  # a promotion: spent first
    DAILY = "daily"  # the day's allowance, with the metrics bonus
    ONE_OFF = "one_off"  # starter, licence and bundle credits
    GRACE = "grace"  # the small allowance after everything else is used


class _LedgerKind(StrEnum):
    """What a ledger row records."""

    GRANT = "grant"
    CHARGE = "charge"
    REFUND = "refund"
    EXPIRE = "expire"


class _PageState(StrEnum):
    """Whether a page's text is final."""

    DONE = "done"
    WAITING = "waiting"  # needs OCR that hasn't been started or sent
    DISPATCHED = "dispatched"  # the OCR is in a remote job


class _JobPageState(StrEnum):
    """Where one image of a remote job is."""

    STAGED = "staged"  # paid for, waiting to be sent in a job
    SENT = "sent"  # in a job the tier is working on
    DONE = "done"  # its result was imported
    FAILED = "failed"  # the tier returned nothing for it
