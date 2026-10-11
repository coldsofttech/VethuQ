"""The SQL objects the search index needs that SQLAlchemy models can't describe: the full-text
table over `page_search` and the triggers that keep it, and the index, in step with the pages."""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError

_logger = logging.getLogger("vethuq.database")


class _SearchDdl:
    FTS_TABLE = "page_search_fts"

    # The trigger on the pages needs no full-text table, so it is always installed: a page whose
    # text or status changes loses its row in `page_search`.
    STALE = (
        "CREATE TRIGGER IF NOT EXISTS pdf_pages_search_stale "
        "AFTER UPDATE OF text, status ON pdf_pages "
        "BEGIN DELETE FROM page_search WHERE page_id = old.id; END"
    )
    FTS = (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
        "norm_text, content='page_search', content_rowid='page_id', tokenize='trigram')"
    )
    TRIGGERS = (
        "CREATE TRIGGER IF NOT EXISTS page_search_ai AFTER INSERT ON page_search BEGIN "  # noqa: S608 - fixed names and bound values
        f"INSERT INTO {FTS_TABLE}(rowid, norm_text) VALUES (new.page_id, new.norm_text); END",
        "CREATE TRIGGER IF NOT EXISTS page_search_ad AFTER DELETE ON page_search BEGIN "  # noqa: S608 - fixed names and bound values
        f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, norm_text) "
        "VALUES ('delete', old.page_id, old.norm_text); END",
    )

    @staticmethod
    def install(connection: Connection) -> None:
        """Create what is missing. A SQLite without the trigram tokenizer (before 3.34) gets no
        full-text table: searches then narrow pages with a plain substring test instead."""
        connection.execute(text(_SearchDdl.STALE))
        try:
            connection.execute(text(_SearchDdl.FTS))
        except OperationalError:
            _logger.warning("SQLite has no FTS5 trigram index; searches will scan pages")
            return
        for statement in _SearchDdl.TRIGGERS:
            connection.execute(text(statement))

    @staticmethod
    def has_fts(connection: Connection) -> bool:
        return (
            connection.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
                {"n": _SearchDdl.FTS_TABLE},
            ).first()
            is not None
        )
