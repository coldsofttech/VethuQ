"""The database schema and its version, recorded in the `schema_version` table."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Connection, Engine, func, inspect, select, update

from vethuq._db.migration import _Migration
from vethuq._db.models import _Base, _SchemaVersion
from vethuq._errors import _SchemaVersionError


class _Schema:
    # The schema version this build reads and writes. Raise it, and add a step to
    # `_Migration.STEPS`, whenever the tables change.
    VERSION = 1

    _logger = logging.getLogger("vethuq.database")

    @staticmethod
    def stored_version(connection: Connection) -> int | None:
        """The version recorded in the database, or None if it has none yet."""
        if not inspect(connection).has_table(_SchemaVersion.__tablename__):
            return None
        return connection.execute(select(func.max(_SchemaVersion.version))).scalar()

    @staticmethod
    def check_not_newer(stored: int | None) -> None:
        """Refuse a database written by a newer VethuQ, before touching it."""
        if stored is not None and stored > _Schema.VERSION:
            _Schema._logger.error(
                "Refusing to open database: schema v%d is newer than supported v%d",
                stored,
                _Schema.VERSION,
            )
            raise _SchemaVersionError(
                f"The database schema (version {stored}) is newer than this version "
                f"of VethuQ supports (version {_Schema.VERSION}).",
                "Upgrade VethuQ to open this database.",
            )

    @staticmethod
    def ensure(engine: Engine, before_migration: Callable[[int, int], None] | None = None) -> None:
        """Create the tables, record the schema version, and migrate an older database.

        `before_migration(stored, target)`, if given, is called first when the database is about
        to be migrated; a failure in it is logged, never raised. Raises `SchemaVersionError` if
        the database is newer than this build supports.
        """
        if before_migration is not None:
            with engine.connect() as connection:
                stored = _Schema.stored_version(connection)
            if stored is not None and stored < _Schema.VERSION:
                try:
                    before_migration(stored, _Schema.VERSION)
                except Exception:  # noqa: BLE001 - a hook must never stop the migration
                    _Schema._logger.warning("Before-migration hook failed", exc_info=True)
        with engine.begin() as connection:
            stored = _Schema.stored_version(connection)
            _Schema.check_not_newer(stored)
            _Base.metadata.create_all(connection)
            if stored is None:
                _Schema._logger.info("Created database schema v%d", _Schema.VERSION)
                connection.execute(
                    _SchemaVersion.__table__.insert().values(version=_Schema.VERSION)
                )
            elif stored < _Schema.VERSION:
                _Schema._logger.info(
                    "Migrating database schema from v%d to v%d", stored, _Schema.VERSION
                )
                _Migration.run(connection, stored, _Schema.VERSION)
                connection.execute(update(_SchemaVersion).values(version=_Schema.VERSION))
