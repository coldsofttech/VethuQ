"""VethuQ's data-access layer - the only place in the codebase that runs SQL.

Every other module talks to SQLite through the query functions re-exported
here (grouped into submodules by table) rather than importing `sqlite3` or
calling `conn.execute`/`conn.executemany`/`conn.executescript` itself.
`connection` additionally owns the connection/schema/migration lifecycle.
"""

from __future__ import annotations

from vethuq_core.db.connection import Db
from vethuq_core.errors import SchemaVersionError

__all__ = [
    "Db",
    "SchemaVersionError",
]
