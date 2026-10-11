"""Internal database layer: models, schema and the connection."""

from __future__ import annotations

from vethuq._db.database import _Database
from vethuq._db.integrity import IntegrityCheckResult, _IntegrityCheck
from vethuq._db.migration import _Migration
from vethuq._db.models import (
    _Base,
    _CreditGrant,
    _CreditLedger,
    _CsvPage,
    _Document,
    _DocumentIndex,
    _DocumentLanguage,
    _IndexRun,
    _Language,
    _MarkdownPage,
    _PageSearch,
    _PdfPage,
    _PdfPagePhase,
    _PdfPageQuick,
    _RemoteJob,
    _RemoteJobPage,
    _SchemaVersion,
    _Setting,
    _Source,
    _SourceLanguage,
    _TxtPage,
    _UsageDaily,
    _UsageFailure,
)
from vethuq._db.schema import _Schema
from vethuq._db.search_index import _SearchDdl

__all__ = [
    "IntegrityCheckResult",
    "_Base",
    "_CreditGrant",
    "_CreditLedger",
    "_CsvPage",
    "_Database",
    "_Document",
    "_DocumentIndex",
    "_DocumentLanguage",
    "_IndexRun",
    "_PageSearch",
    "_MarkdownPage",
    "_PdfPage",
    "_PdfPagePhase",
    "_PdfPageQuick",
    "_RemoteJob",
    "_RemoteJobPage",
    "_IntegrityCheck",
    "_Language",
    "_Migration",
    "_Schema",
    "_SearchDdl",
    "_SchemaVersion",
    "_Setting",
    "_Source",
    "_SourceLanguage",
    "_TxtPage",
    "_UsageDaily",
    "_UsageFailure",
]
