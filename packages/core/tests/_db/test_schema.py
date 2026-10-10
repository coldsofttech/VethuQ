from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, select, text

from vethuq import errors
from vethuq._db import _Database, _Migration, _Schema, _SchemaVersion, _Source


def _stored(database):
    with database.session() as session:
        return list(session.scalars(select(_SchemaVersion.version)))


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "db" / "vethuq.db"


@pytest.fixture
def database(db_path):
    database = _Database(db_path)
    yield database
    database.dispose()


def _stamp(db_path, version):
    """Write a database as another version of VethuQ would have left it."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


class TestSchemaVersionTable:
    def test_a_new_database_records_the_current_version(self, database):
        assert _stored(database) == [_Schema.VERSION]

    def test_the_first_version_is_one(self):
        assert _Schema.VERSION == 1

    def test_opening_again_keeps_a_single_row(self, db_path):
        for _ in range(3):
            database = _Database(db_path)
            assert _stored(database) == [_Schema.VERSION]
            database.dispose()

    def test_the_table_has_a_single_integer_column(self, database):
        with database.session() as session:
            columns = session.execute(text("PRAGMA table_info(schema_version)")).all()

        assert [(c.name, c.type) for c in columns] == [("version", "INTEGER")]

    def test_a_database_without_the_table_is_stamped(self, db_path):
        db_path.parent.mkdir(parents=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY)")  # a pre-versioning file
        database = _Database(db_path)

        assert _stored(database) == [_Schema.VERSION]
        database.dispose()

    def test_an_empty_table_is_filled(self, db_path):
        db_path.parent.mkdir(parents=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
        database = _Database(db_path)

        assert _stored(database) == [_Schema.VERSION]
        database.dispose()

    def test_stored_version_is_none_before_the_table_exists(self, db_path):
        db_path.parent.mkdir(parents=True)
        sqlite3.connect(db_path).close()

        with create_engine(f"sqlite:///{db_path}").connect() as connection:
            assert _Schema.stored_version(connection) is None


class TestNewerSchema:
    def test_a_database_from_a_newer_vethuq_is_refused(self, db_path):
        _stamp(db_path, _Schema.VERSION + 1)
        database = _Database(db_path)

        with pytest.raises(errors.SchemaVersionError) as excinfo:
            with database.session():
                pass

        assert f"version {_Schema.VERSION + 1}" in excinfo.value.message
        assert f"version {_Schema.VERSION}" in excinfo.value.message
        assert "Upgrade VethuQ" in excinfo.value.hint
        assert excinfo.value.exit_code == 14
        assert isinstance(excinfo.value, errors.StartupError)

    def test_a_refused_database_is_left_untouched(self, db_path):
        _stamp(db_path, _Schema.VERSION + 1)
        database = _Database(db_path)

        with pytest.raises(errors.SchemaVersionError):
            with database.session():
                pass

        with sqlite3.connect(db_path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            assert "sources" not in tables
            assert conn.execute("SELECT version FROM schema_version").fetchall() == [
                (_Schema.VERSION + 1,)
            ]

    def test_it_is_refused_every_time(self, db_path):
        _stamp(db_path, _Schema.VERSION + 5)
        database = _Database(db_path)

        for _ in range(2):
            with pytest.raises(errors.SchemaVersionError):
                with database.session():
                    pass

    def test_the_same_version_is_accepted(self, db_path):
        _stamp(db_path, _Schema.VERSION)
        database = _Database(db_path)

        assert _stored(database) == [_Schema.VERSION]
        database.dispose()


class TestMigration:
    @pytest.fixture
    def raised(self, monkeypatch):
        """Pretend this build is at schema version 3, with steps for versions 2 and 3."""
        calls = []
        monkeypatch.setattr(_Schema, "VERSION", 3)
        monkeypatch.setattr(
            _Migration,
            "STEPS",
            {
                2: lambda connection: calls.append(2),
                3: lambda connection: calls.append(3),
            },
        )
        return calls

    def test_an_older_database_is_migrated_step_by_step(self, db_path, raised):
        _stamp(db_path, 1)
        database = _Database(db_path)

        assert _stored(database) == [3]
        assert raised == [2, 3]
        database.dispose()

    def test_only_the_missing_steps_run(self, db_path, raised):
        _stamp(db_path, 2)
        database = _Database(db_path)

        assert _stored(database) == [3]
        assert raised == [3]
        database.dispose()

    def test_a_current_database_runs_no_steps(self, db_path, raised):
        _stamp(db_path, 3)
        database = _Database(db_path)

        assert _stored(database) == [3]
        assert raised == []
        database.dispose()

    def test_a_version_without_a_step_is_just_recorded(self, db_path, monkeypatch):
        monkeypatch.setattr(_Schema, "VERSION", 2)
        _stamp(db_path, 1)
        database = _Database(db_path)

        assert _stored(database) == [2]
        database.dispose()

    def test_a_failing_step_leaves_the_version_alone(self, db_path, monkeypatch):
        monkeypatch.setattr(_Schema, "VERSION", 2)

        def broken(connection):
            connection.execute(text("INSERT INTO languages (language) VALUES ('zz')"))
            raise RuntimeError("step failed")

        monkeypatch.setattr(_Migration, "STEPS", {2: broken})
        _stamp(db_path, 1)
        database = _Database(db_path)

        with pytest.raises(RuntimeError, match="step failed"):
            with database.session():
                pass

        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
            assert conn.execute("SELECT COUNT(*) FROM languages").fetchone() == (0,)

    def test_run_applies_steps_in_version_order(self, monkeypatch):
        order = []
        monkeypatch.setattr(
            _Migration, "STEPS", {5: lambda c: order.append(5), 3: lambda c: order.append(3)}
        )

        _Migration.run(None, 2, 5)

        assert order == [3, 5]

    def test_the_default_steps_are_empty(self):
        assert _Migration.STEPS == {}


class TestSchemaIsUsable:
    def test_the_other_tables_are_created_alongside(self, database):
        with database.session() as session:
            session.add(_Source(path="p", source_type="file", added_at="t"))

        with database.session() as session:
            assert len(session.scalars(select(_Source)).all()) == 1
