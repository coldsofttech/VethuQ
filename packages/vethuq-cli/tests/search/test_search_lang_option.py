"""`vethuq search --lang`: only results on pages read in the chosen language."""

import pytest
import vethuq_core.db as db_module
from test_search_commands import _flatten, _seed_indexed_pdf
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)


@pytest.fixture
def mixed_db(use_temp_db):
    db_path = use_temp_db()
    english = _seed_indexed_pdf(db_path, "/docs/english.pdf", "invoice total")
    telugu = _seed_indexed_pdf(db_path, "/docs/telugu.pdf", "అమ్మ invoice")
    conn = db_module.Db.connect(db_path)
    try:
        conn.execute("UPDATE pdf_pages SET language = 'en' WHERE document_id = ?", (english,))
        conn.execute(
            "UPDATE pdf_pages SET language = 'te', ocr_langs = 'te' WHERE document_id = ?",
            (telugu,),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


class TestLangOption:
    def test_without_it_every_language_is_searched(self, mixed_db):
        output = _flatten(runner.invoke(app, ["search", "invoice"]).output)

        assert "english.pdf" in output and "telugu.pdf" in output

    def test_telugu_keeps_only_telugu_pages(self, mixed_db):
        result = runner.invoke(app, ["search", "invoice", "--lang", "te"])

        output = _flatten(result.output)
        assert result.exit_code == 0
        assert "telugu.pdf" in output and "english.pdf" not in output

    @pytest.mark.parametrize("engine", ["like", "exact", "full-text"])
    def test_it_works_with_a_single_engine(self, mixed_db, engine):
        result = runner.invoke(app, ["search", "invoice", "--engine", engine, "--lang", "en"])

        output = _flatten(result.output)
        assert "english.pdf" in output and "telugu.pdf" not in output

    def test_languages_can_be_repeated_or_comma_separated(self, mixed_db):
        for args in (["--lang", "en", "--lang", "te"], ["--lang", "en,te"]):
            output = _flatten(runner.invoke(app, ["search", "invoice", *args]).output)

            assert "english.pdf" in output and "telugu.pdf" in output

    def test_no_match_in_the_language_says_so(self, mixed_db):
        result = runner.invoke(app, ["search", "total", "--lang", "te"])

        assert "No matches found" in _flatten(result.output)

    def test_an_unknown_language_is_a_usage_error(self, mixed_db):
        result = runner.invoke(app, ["search", "invoice", "--lang", "xx"])

        assert result.exit_code == 2
        assert "Unknown language" in _flatten(result.output)
