"""The database connection: one SQLAlchemy engine and session factory per database file."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from vethuq._db.integrity import _IntegrityCheck
from vethuq._db.schema import _Schema
from vethuq._errors import _CorruptDatabaseError
from vethuq._logs import _DatabaseLog
from vethuq._paths import _Paths
from vethuq._paths.device import _DeviceFolder, _DeviceLocation


class _DatabaseHooks(Protocol):
    """What the database calls at its key moments (implemented by the add-on manager)."""

    def on_open(self) -> None: ...

    def before_migration(self, stored: int, target: int) -> None: ...


class _Database:
    BUSY_TIMEOUT_MS = 5000

    _logger = logging.getLogger("vethuq.database")

    def __init__(
        self,
        db_path: Path,
        on_open: Callable[[Session], None] | None = None,
        hooks: _DatabaseHooks | None = None,
    ) -> None:
        """`on_open`, if given, runs once each time the database is opened, with a session. It is
        for maintenance: a failure in it is logged, never raised. `hooks` are told when the
        database is about to be migrated and when it has been opened; they never raise either."""
        self.db_path = Path(db_path)
        self._on_open = on_open
        self._hooks = hooks
        self._engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None
        self._open_error: _CorruptDatabaseError | None = None
        self._lock = threading.Lock()
        self.device: _DeviceLocation | None = None  # set once the database is opened

    @staticmethod
    def _configure_connection(dbapi_connection: Any, _record: Any) -> None:
        """Foreign keys on, WAL journal (clean recovery after a crash), and a busy timeout so
        readers and writers on separate connections wait instead of failing."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute(f"PRAGMA busy_timeout = {_Database.BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    @staticmethod
    def _attach_device(file: Path) -> Callable[[Any, Any], None]:
        """A connect hook that attaches the device database as schema `device`: the credit ledger
        lives there, so every account on the computer shares it (see `_DeviceFolder`). It keeps a
        rollback journal, not WAL, so accounts with different rights can all use it."""

        def attach(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("ATTACH DATABASE ? AS device", (str(file),))
                cursor.execute("PRAGMA device.journal_mode = DELETE")
            finally:
                cursor.close()

        return attach

    # Statements that take SQLite's write lock.
    _WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")

    @staticmethod
    def _lock_both_databases(engine: Engine) -> None:
        """Take the write lock on the main and the device database, in that order, at the first
        write of every transaction.

        A transaction that writes to both takes their locks as its statements run. Two such
        transactions that take them in opposite orders deadlock, and SQLite reports that at once
        (`database is locked`) instead of waiting for the busy timeout. Locking both up front, in
        one fixed order, makes them queue behind each other instead. A no-op `DELETE ... WHERE 0`
        takes the lock without changing anything.
        """

        @event.listens_for(engine, "begin")
        def begun(connection: Any) -> None:
            connection.info["write_locked"] = False

        @event.listens_for(engine, "before_cursor_execute")
        def before(connection: Any, cursor: Any, statement: str, *_rest: Any) -> None:
            if connection.info.get("write_locked", True):
                return
            if not statement.lstrip().upper().startswith(_Database._WRITES):
                return
            connection.info["write_locked"] = True  # first: the statements below are writes too
            cursor.execute("DELETE FROM main.schema_version WHERE 0")
            cursor.execute("DELETE FROM device.credit_grants WHERE 0")

    @staticmethod
    def _corruption_error(exc: BaseException, db_path: Path) -> _CorruptDatabaseError | None:
        """A `CorruptDatabaseError` if `exc` means the file is damaged, else None.

        SQLite reports "file is not a database" and "database disk image is malformed" as a plain
        `DatabaseError`; its subclasses (locked, read-only, ...) are not corruption.
        """
        reason = getattr(exc, "orig", exc)
        if type(reason) is not sqlite3.DatabaseError:
            return None
        _Database._logger.error(
            "Database file is corrupt or not a database: path=%s (%s)", db_path, reason
        )
        return _CorruptDatabaseError(
            f"The VethuQ database at {db_path} is damaged or isn't a database ({reason}).",
            "Restore a backup, or move the file aside to start fresh.",
        )

    def _check_integrity(self) -> None:
        """Run the integrity check if the mode calls for it; a failed check refuses the database."""
        result = _IntegrityCheck.maybe_run(self.db_path)
        if result is None or result.ok:
            return
        first = result.errors[0] if result.errors else "unknown problem"
        more = f" (and {len(result.errors) - 1} more)" if len(result.errors) > 1 else ""
        raise _CorruptDatabaseError(
            f"The VethuQ database at {self.db_path} failed its integrity check: {first}{more}.",
            "Run client.db.integrity_check() for the details, then restore a backup, or move "
            "the file aside to start fresh.",
        )

    def _ready(self) -> sessionmaker[Session]:
        """Create the engine and the tables on first use, and check the database."""
        with self._lock:
            if self._open_error is not None:
                raise self._open_error  # a damaged database stays refused until `dispose()`
            if self._sessions is None:
                _Paths.ensure_writable(self.db_path.parent)
                _DatabaseLog.setup(self.db_path)  # before the schema, so its creation is logged
                device = _DeviceFolder.resolve(self.db_path)
                _DeviceFolder.touch(device)
                engine = create_engine(f"sqlite:///{self.db_path}")
                event.listen(engine, "connect", self._configure_connection)
                event.listen(engine, "connect", self._attach_device(device.database))
                self._lock_both_databases(engine)
                sessions = sessionmaker(engine, expire_on_commit=False)
                try:
                    _Schema.ensure(
                        engine,
                        self._hooks.before_migration if self._hooks is not None else None,
                    )
                    self._check_integrity()
                except _CorruptDatabaseError as exc:
                    engine.dispose()
                    self._open_error = exc
                    raise
                except DatabaseError as exc:
                    engine.dispose()
                    corrupt = self._corruption_error(exc, self.db_path)
                    if corrupt is not None:
                        self._open_error = corrupt
                        raise corrupt from exc
                    raise
                except BaseException:
                    engine.dispose()
                    raise
                self._engine = engine
                self._sessions = sessions
                self.device = device
                self._maintain(sessions)
            return self._sessions

    def _maintain(self, sessions: sessionmaker[Session]) -> None:
        if self._on_open is not None:
            try:
                with sessions() as session:
                    self._on_open(session)
                    session.commit()
            except Exception:  # noqa: BLE001 - maintenance must never get in the way
                self._logger.warning("Maintenance on opening the database failed", exc_info=True)
        if self._hooks is not None:
            try:
                self._hooks.on_open()
            except Exception:  # noqa: BLE001 - hooks are best effort
                self._logger.warning("Hooks on opening the database failed", exc_info=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session that commits when the block ends and rolls back if it raises."""
        with self._ready()() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def dispose(self) -> None:
        """Release the connections. The database can still be used; it reconnects on demand."""
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()
            self._engine = None
            self._sessions = None
            self._open_error = None
