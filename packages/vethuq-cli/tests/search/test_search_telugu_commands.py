"""`vethuq search` with Telugu text."""

import pytest
from test_search_commands import _flatten, _seed_indexed_pdf
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.storage.sqlite import SqliteStorage

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)


@pytest.fixture
def telugu_db(use_temp_db):
    db_path = use_temp_db()
    _seed_indexed_pdf(db_path, "/docs/amma.pdf", "అమ్మ ఇంటికి వెళ్ళింది")
    _seed_indexed_pdf(db_path, "/docs/kaki.pdf", "కాకి చెట్టు మీద కూర్చుంది")
    _seed_indexed_pdf(db_path, "/docs/english.pdf", "Museum of art")
    return db_path


class TestTeluguSearch:
    def test_a_telugu_query_finds_the_file_and_shows_the_word(self, telugu_db):
        result = runner.invoke(app, ["search", "కాకి"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "kaki.pdf" in output
        assert "కాకి" in output
        assert "amma.pdf" not in output

    @pytest.mark.parametrize("engine", ["like", "exact", "full-text", "fuzzy", "noise-fuzzy"])
    def test_every_engine_finds_it(self, telugu_db, engine):
        result = runner.invoke(app, ["search", "అమ్మ", "--engine", engine])

        assert result.exit_code == 0
        assert "amma.pdf" in _flatten(result.output)

    def test_proximity_finds_two_telugu_words(self, telugu_db):
        result = runner.invoke(app, ["search", "అమ్మ వెళ్ళింది", "--engine", "proximity"])

        assert result.exit_code == 0
        assert "amma.pdf" in _flatten(result.output)

    def test_a_part_of_a_word_is_not_a_whole_word_match(self, telugu_db):
        result = runner.invoke(app, ["search", "కా", "--engine", "exact"])

        assert "No matches found" in _flatten(result.output)

    def test_an_english_search_is_unchanged(self, telugu_db):
        result = runner.invoke(app, ["search", "museum"])

        assert result.exit_code == 0
        assert "english.pdf" in _flatten(result.output)


class TestOldSqlite:
    @pytest.fixture(autouse=True)
    def _old_sqlite(self, monkeypatch):
        monkeypatch.setattr(SqliteStorage, "has_complex_word_index", lambda self: False)

    def test_naming_the_engine_says_why_it_cannot_search_telugu(self, telugu_db):
        result = runner.invoke(app, ["search", "కాకి", "--engine", "full-text"])

        assert result.exit_code == 1
        assert "newer SQLite" in _flatten(result.output)

    def test_the_combined_search_still_finds_it(self, telugu_db):
        result = runner.invoke(app, ["search", "కాకి"])

        assert result.exit_code == 0
        assert "kaki.pdf" in _flatten(result.output)
