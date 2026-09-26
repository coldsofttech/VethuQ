import sqlite3

import pytest
from vethuq_core.db import connect
from vethuq_core.settings import (
    get_search_snippet_context_chars,
    get_setting,
    is_gpu_enabled,
    set_gpu_enabled,
    set_search_snippet_context_chars,
    set_setting,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = connect(db_path)
    yield connection
    connection.close()


def test_gpu_disabled_by_default(conn: sqlite3.Connection):
    assert is_gpu_enabled(conn) is False


def test_set_gpu_enabled_roundtrip(conn: sqlite3.Connection):
    set_gpu_enabled(conn, True)
    assert is_gpu_enabled(conn) is True

    set_gpu_enabled(conn, False)
    assert is_gpu_enabled(conn) is False


def test_set_setting_overwrites_existing_value(conn: sqlite3.Connection):
    set_setting(conn, "key", "first")
    set_setting(conn, "key", "second")

    assert get_setting(conn, "key") == "second"


def test_get_setting_missing_key_returns_none(conn: sqlite3.Connection):
    assert get_setting(conn, "does-not-exist") is None


def test_search_snippet_context_chars_defaults_to_80(conn: sqlite3.Connection):
    assert get_search_snippet_context_chars(conn) == 80


def test_set_search_snippet_context_chars_roundtrip(conn: sqlite3.Connection):
    set_search_snippet_context_chars(conn, 40)
    assert get_search_snippet_context_chars(conn) == 40


def test_set_search_snippet_context_chars_rejects_negative(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="non-negative"):
        set_search_snippet_context_chars(conn, -1)
