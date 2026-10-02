"""SQL for `PRAGMA integrity_check`."""

from __future__ import annotations

import sqlite3


class Integrity:
    @staticmethod
    def run_pragma(conn: sqlite3.Connection) -> list[str]:
        """Run `PRAGMA integrity_check` and return SQLite's raw result rows.

        A single 'ok' entry means the database is intact; anything else is one
        or more specific corruption messages (e.g. a bad page, a broken index).
        """
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        return [row[0] for row in rows]
