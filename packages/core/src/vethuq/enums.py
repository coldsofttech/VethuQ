"""The fixed sets of values used across VethuQ's public API."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["SortOrder", "SourceSortBy", "SourceStatus", "SourceType"]


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
