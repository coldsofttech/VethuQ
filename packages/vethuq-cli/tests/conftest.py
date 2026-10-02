from pathlib import Path

import pytest
from vethuq_core.db import Db
from vethuq_core.paths import Paths


@pytest.fixture
def use_temp_db(monkeypatch, tmp_path):
    """Returns a callable that points every `Db.connect()` at a temp database.

    Calling it returns the database path, for tests that need to seed data first.
    """

    def _use() -> Path:
        db_path = tmp_path / "vethuq.db"
        real_connect = Db.connect
        monkeypatch.setattr(
            Db,
            "connect",
            staticmethod(lambda path=None, **kwargs: real_connect(db_path, **kwargs)),
        )
        monkeypatch.setattr(Db, "default_db_path", staticmethod(lambda: db_path))
        return db_path

    return _use


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path_factory, monkeypatch):
    """Keep tests from creating db/, run/ or logs/ folders in the real per-user data dir."""
    root = tmp_path_factory.mktemp("data_root")
    monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: root))
