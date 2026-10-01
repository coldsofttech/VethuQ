import sqlite3

import pytest
from vethuq_core.db import Db
from vethuq_core.settings import GpuSettings, IndexSettings, SearchSettings, Settings


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = Db.connect(db_path)
    yield connection
    connection.close()


def test_gpu_disabled_by_default(conn: sqlite3.Connection):
    assert GpuSettings.is_enabled(conn) is False


def test_set_gpu_enabled_roundtrip(conn: sqlite3.Connection):
    GpuSettings.set_enabled(conn, True)
    assert GpuSettings.is_enabled(conn) is True

    GpuSettings.set_enabled(conn, False)
    assert GpuSettings.is_enabled(conn) is False


def test_set_setting_overwrites_existing_value(conn: sqlite3.Connection):
    Settings.set(conn, "key", "first")
    Settings.set(conn, "key", "second")

    assert Settings.get(conn, "key") == "second"


def test_search_export_format_defaults_to_json(conn: sqlite3.Connection):
    assert SearchSettings.get_export_format(conn) == "json"


def test_set_search_export_format_roundtrip(conn: sqlite3.Connection):
    SearchSettings.set_export_format(conn, "html")
    assert SearchSettings.get_export_format(conn) == "html"


def test_set_search_export_format_rejects_unsupported_format(conn: sqlite3.Connection):
    with pytest.raises(ValueError):
        SearchSettings.set_export_format(conn, "xml")


def test_get_setting_missing_key_returns_none(conn: sqlite3.Connection):
    assert Settings.get(conn, "does-not-exist") is None


def test_search_snippet_context_chars_defaults_to_80(conn: sqlite3.Connection):
    assert SearchSettings.get_snippet_context_chars(conn) == 80


def test_set_search_snippet_context_chars_roundtrip(conn: sqlite3.Connection):
    SearchSettings.set_snippet_context_chars(conn, 40)
    assert SearchSettings.get_snippet_context_chars(conn) == 40


def test_set_search_snippet_context_chars_rejects_negative(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="non-negative"):
        SearchSettings.set_snippet_context_chars(conn, -1)


def test_thread_workers_defaults_to_disabled(conn: sqlite3.Connection):
    assert IndexSettings.get_thread_workers(conn) == "0"


@pytest.mark.parametrize("value", ["0", "1", "8", "auto"])
def test_set_thread_workers_roundtrip(conn: sqlite3.Connection, value: str):
    IndexSettings.set_thread_workers(conn, value)
    assert IndexSettings.get_thread_workers(conn) == value


@pytest.mark.parametrize("value", ["-1", "9", "abc", ""])
def test_set_thread_workers_rejects_out_of_range_value(conn: sqlite3.Connection, value: str):
    with pytest.raises(ValueError):
        IndexSettings.set_thread_workers(conn, value)
