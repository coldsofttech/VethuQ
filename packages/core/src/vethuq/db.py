"""The database: `VethuQ().db`.

    result = client.db.integrity_check()
    if not result.ok:
        print(result.errors)
"""

from __future__ import annotations

from vethuq._db import IntegrityCheckResult, _Database, _IntegrityCheck
from vethuq.enums import IntegrityCheckMode

__all__ = ["Db", "IntegrityCheckMode", "IntegrityCheckResult"]


class Db:
    """Checks on the database file.

    Not created directly: use `VethuQ().db`. These work on the file itself, so they still run on a
    database VethuQ refuses to open because it is damaged.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def integrity_check(self, *, quick: bool = False) -> IntegrityCheckResult:
        """Check the database for corruption now, whatever the automatic mode is.

        Runs `PRAGMA integrity_check`, which verifies every page and that every index matches its
        table; it takes about as long as reading the whole file. With `quick=True` it runs
        `PRAGMA quick_check` instead: faster, but it doesn't verify index contents. A damaged
        database gives `ok=False` with SQLite's messages in `errors`; nothing is raised. The
        result is saved (see `integrity_status`) and logged to the `database` log.

        If there is no database yet it is created first.
        """
        if not self._database.db_path.exists():
            with self._database.session():  # creates the database
                pass
        return _IntegrityCheck.run(self._database.db_path, quick=quick)

    def integrity_status(self) -> IntegrityCheckResult | None:
        """The result of the last integrity check, automatic or on demand, without checking again.

        None if there hasn't been one.
        """
        return _IntegrityCheck.status(self._database.db_path)
