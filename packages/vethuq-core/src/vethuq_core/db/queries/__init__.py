"""Per-table SQL query classes - the only place in the codebase that runs SQL."""

from __future__ import annotations

from vethuq_core.db.queries.documents import Document
from vethuq_core.db.queries.index import Index
from vethuq_core.db.queries.ocr import Ocr
from vethuq_core.db.queries.settings import Settings
from vethuq_core.db.queries.sources import Source
from vethuq_core.db.queries.stats import Stats

__all__ = ["Document", "Index", "Ocr", "Settings", "Source", "Stats"]
