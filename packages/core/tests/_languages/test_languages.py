from __future__ import annotations

import pytest

from vethuq._db import _Database, _Language
from vethuq._languages import _Languages


class TestListAll:
    @pytest.fixture
    def database(self, tmp_path):
        database = _Database(tmp_path / "db" / "vethuq.db")
        yield database
        database.dispose()

    @staticmethod
    def _codes(database):
        with database.session() as session:
            return [(row.id, row.language) for row in _Languages.list_all(session)]

    def test_lists_the_seeded_english(self, database):
        assert self._codes(database) == [(1, "en")]

    def test_lists_added_languages_in_language_order(self, database):
        with database.session() as session:
            session.add_all([_Language(language="te"), _Language(language="hi")])

        assert self._codes(database) == [(1, "en"), (2, "te"), (3, "hi")]

    def test_rows_stay_usable_after_the_session_closes(self, database):
        with database.session() as session:
            rows = _Languages.list_all(session)

        assert [row.language for row in rows] == ["en"]
