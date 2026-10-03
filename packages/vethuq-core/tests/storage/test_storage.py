import ast
import sqlite3
from pathlib import Path

import pytest
import vethuq_core
from vethuq_core.sources import Sources
from vethuq_core.storage import SqliteStorage, Storage, open_storage

CORE_SRC = Path(vethuq_core.__file__).parent


def test_open_storage_returns_a_working_storage(tmp_path):
    storage = open_storage(tmp_path / "vethuq.db")
    try:
        assert isinstance(storage, SqliteStorage)
        assert storage.get_setting_value("gpu_enabled") is None
        storage.upsert_setting("gpu_enabled", "true")
        assert storage.get_setting_value("gpu_enabled") == "true"
    finally:
        storage.close()


def test_storage_is_usable_wherever_a_conn_used_to_be(tmp_path):
    storage: Storage = open_storage(tmp_path / "vethuq.db")
    try:
        Sources.add(storage, tmp_path)
        assert [s.path for s in Sources.list_all(storage)] == [str(tmp_path.resolve())]
    finally:
        storage.close()


def test_transaction_commits_on_success_and_rolls_back_on_error(tmp_path):
    storage = open_storage(tmp_path / "vethuq.db")
    try:
        with storage.transaction():
            storage.insert_source("/kept", "folder", "2026-01-01T00:00:00+00:00")
        with pytest.raises(RuntimeError), storage.transaction():
            storage.insert_source("/dropped", "folder", "2026-01-01T00:00:00+00:00")
            raise RuntimeError("boom")
        assert storage.get_source_by_path("/kept") is not None
        assert storage.get_source_by_path("/dropped") is None
    finally:
        storage.close()


def test_close_closes_the_underlying_connection(tmp_path):
    storage = open_storage(tmp_path / "vethuq.db")
    storage.close()
    with pytest.raises(sqlite3.ProgrammingError):
        storage.get_setting_value("a")


def test_sqlite_storage_implements_every_storage_method():
    from vethuq_core.storage import base

    protocol_methods = {
        name
        for proto in (
            base.SourceStore,
            base.DocumentStore,
            base.SettingsStore,
            base.StatsStore,
            base.IndexRunStore,
            base.OcrStore,
            base.IntegrityStore,
            base.Storage,
        )
        for name in vars(proto)
        if not name.startswith("_")
    }
    assert protocol_methods
    assert all(callable(getattr(SqliteStorage, name, None)) for name in protocol_methods)


def test_only_the_storage_layer_touches_sqlite():
    """Application modules depend on `Storage`, never on `sqlite3` or `vethuq_core.db`."""
    allowed = {"db", "storage"}
    # logs.py reads one setting before any connection (or schema) exists.
    bootstrap = {"logs.py"}
    offenders = []
    for path in CORE_SRC.rglob("*.py"):
        rel = path.relative_to(CORE_SRC)
        if rel.parts[0] in allowed or rel.name in bootstrap:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            if any(m == "sqlite3" or m.startswith("vethuq_core.db") for m in modules):
                offenders.append(str(rel))
    assert offenders == []
