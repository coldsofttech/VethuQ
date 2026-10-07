"""`vethuq search` shows Unicode file names and text unchanged, and finds them in every engine."""

import unicodedata

import pytest
from test_search_commands import _flatten, _seed_indexed_pdf
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app

runner = CliRunner()

DECOMPOSED_CAFE = unicodedata.normalize("NFD", "café")


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)


@pytest.fixture
def unicode_db(use_temp_db):
    db_path = use_temp_db()
    _seed_indexed_pdf(db_path, "/docs/été-menu.pdf", "Visit the café on Rue Saint-Honoré")
    _seed_indexed_pdf(db_path, "/docs/привет.pdf", "Привет мир, добро пожаловать")
    _seed_indexed_pdf(db_path, "/docs/東京.pdf", "東京都の美術館を訪れる")
    _seed_indexed_pdf(db_path, "/docs/decomposed.pdf", f"a {DECOMPOSED_CAFE} downtown")
    _seed_indexed_pdf(db_path, "/docs/english.pdf", "Museum of art")
    return db_path


class TestUnicodeOutput:
    def test_shows_accented_text_and_file_name_unchanged(self, unicode_db):
        result = runner.invoke(app, ["search", "Honoré"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "été-menu.pdf" in output
        assert "Rue Saint-Honoré" in output

    def test_shows_cyrillic_unchanged(self, unicode_db):
        result = runner.invoke(app, ["search", "мир"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "привет.pdf" in output
        assert "Привет мир, добро пожаловать" in output

    def test_shows_cjk_unchanged(self, unicode_db):
        result = runner.invoke(app, ["search", "美術館"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "東京.pdf" in output
        assert "東京都の美術館を訪れる" in output

    def test_a_decomposed_match_is_shown_as_stored(self, unicode_db):
        result = runner.invoke(app, ["search", "café", "--engine", "like"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert DECOMPOSED_CAFE in output
        assert "été-menu.pdf" in output and "decomposed.pdf" in output


class TestUnicodeQueries:
    @pytest.mark.parametrize("engine", ["like", "exact", "full-text", "fuzzy", "noise-fuzzy"])
    @pytest.mark.parametrize(
        ("query", "file_name"),
        [("добро", "привет.pdf"), ("Honoré", "été-menu.pdf")],
    )
    def test_engines_find_unicode_words(self, unicode_db, engine, query, file_name):
        result = runner.invoke(app, ["search", query, "--engine", engine])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert file_name in output
        assert query in output

    @pytest.mark.parametrize("engine", ["like", "lexical"])
    def test_substring_engines_find_cjk(self, unicode_db, engine):
        result = runner.invoke(app, ["search", "美術館", "--engine", engine])

        assert result.exit_code == 0
        assert "東京.pdf" in _flatten(result.output)

    def test_proximity_finds_two_unicode_words(self, unicode_db):
        result = runner.invoke(app, ["search", "привет мир", "--engine", "proximity"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "привет.pdf" in output
        assert "Привет мир" in output

    @pytest.mark.parametrize("query", ["ПРИВЕТ", "привет"])
    def test_case_is_ignored(self, unicode_db, query):
        result = runner.invoke(app, ["search", query])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "привет.pdf" in output
        assert "Привет" in output

    def test_a_composed_query_finds_decomposed_text(self, unicode_db):
        result = runner.invoke(app, ["search", "café", "--engine", "exact"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "decomposed.pdf" in output and "été-menu.pdf" in output

    def test_a_decomposed_query_finds_composed_text(self, unicode_db):
        result = runner.invoke(app, ["search", DECOMPOSED_CAFE, "--engine", "exact"])

        assert result.exit_code == 0
        output = _flatten(result.output)
        assert "été-menu.pdf" in output and "decomposed.pdf" in output

    def test_unrelated_files_are_left_out(self, unicode_db):
        result = runner.invoke(app, ["search", "добро", "--engine", "exact"])

        output = _flatten(result.output)
        assert "english.pdf" not in output
        assert "東京.pdf" not in output
