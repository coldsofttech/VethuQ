"""The database connection: one SQLAlchemy engine and session factory per database file."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from vethuq._db.models import _Base, _Language
from vethuq._paths import _Paths


class _Database:
    BUSY_TIMEOUT_MS = 5000
    # Languages every database starts with; more are added as they become available.
    DEFAULT_LANGUAGES = ("en",)

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None
        self._lock = threading.Lock()

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

    def _ready(self) -> sessionmaker[Session]:
        """Create the engine and the tables on first use."""
        with self._lock:
            if self._sessions is None:
                _Paths.ensure_writable(self.db_path.parent)
                engine = create_engine(f"sqlite:///{self.db_path}")
                event.listen(engine, "connect", self._configure_connection)
                _Base.metadata.create_all(engine)
                self._engine = engine
                self._sessions = sessionmaker(engine, expire_on_commit=False)
                self._seed(self._sessions)
            return self._sessions

    @staticmethod
    def _seed(sessions: sessionmaker[Session]) -> None:
        """Add the default languages that are missing."""
        with sessions() as session:
            known = set(session.scalars(select(_Language.language)))
            session.add_all(
                _Language(language=code)
                for code in _Database.DEFAULT_LANGUAGES
                if code not in known
            )
            session.commit()

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
