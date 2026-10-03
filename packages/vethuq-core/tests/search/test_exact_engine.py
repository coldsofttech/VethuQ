import sqlite3

import pytest
from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.storage import Storage


class TestExactEngine:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("museum", []),
            ("Museum", ["Museum"]),
            ("Museums", []),
            ("Mus", []),
            ("seu", []),
        ],
    )
    def test_is_case_sensitive_and_whole_word(
        self, conn: sqlite3.Connection, storage: Storage, query: str, expected: list[str]
    ):
        SearchData.seed_page(conn, "Visit the Museum today")

        matches = Search.indexed_content(storage, query, engine="exact")

        assert [m.matched for m in matches] == expected

    def test_does_not_match_inside_a_longer_word(self, conn: sqlite3.Connection, storage: Storage):
        SearchData.seed_page(conn, "Museums and the Museum-shop, Museum.")

        matches = Search.indexed_content(storage, "Museum", engine="exact")

        assert [(m.before, m.after) for m in matches] == [
            ("Museums and the ", "-shop, Museum."),
            ("Museums and the Museum-shop, ", "."),
        ]

    def test_matches_symbols_and_phrases_literally(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "Total due: $1,200.00 by Friday (50% off)")

        assert len(Search.indexed_content(storage, "$1,200.00", engine="exact")) == 1
        assert len(Search.indexed_content(storage, "due: $1,200.00", engine="exact")) == 1
        assert len(Search.indexed_content(storage, "50%", engine="exact")) == 1
        assert Search.indexed_content(storage, "$1,20", engine="exact") == []
        assert Search.indexed_content(storage, "", engine="exact") == []

    def test_ignores_case_sensitive_flag(self, conn: sqlite3.Connection, storage: Storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        assert Search.indexed_content(storage, "museum", engine="exact", case_sensitive=False) == []
        assert (
            len(Search.indexed_content(storage, "Museum", engine="exact", case_sensitive=True)) == 1
        )
