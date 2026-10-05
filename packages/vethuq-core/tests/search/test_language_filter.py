"""`--lang`: keeping only the results on pages read in the chosen languages."""

import pytest
from search_data import SearchData
from vethuq_core.db.queries.documents import Document
from vethuq_core.search import Search, SearchLanguageError
from vethuq_core.search.languages import SearchLanguages

BOTH = "Invoice అమ్మ"


@pytest.fixture
def pages(conn):
    """Four single-page files: English, Telugu, one read in both, and an old page with none."""
    for name, text, language, ocr_langs in (
        ("english", "invoice total", "en", ""),
        ("telugu", "అమ్మ ఇల్లు invoice", "te", "te"),
        ("both", BOTH, "te", "en,te"),
        ("old", "invoice from before languages", None, ""),
    ):
        document_id = SearchData.seed_page(conn, text, path=f"/docs/{name}.pdf")
        conn.execute(
            "UPDATE pdf_pages SET language = ?, ocr_langs = ? WHERE document_id = ?",
            (language, ocr_langs, document_id),
        )
    Document.refresh_derived_text(conn, "pdf_pages")
    conn.commit()


def _names(matches) -> list[str]:
    return sorted({m.file_name.removesuffix(".pdf") for m in matches})


class TestParse:
    def test_nothing_and_auto_mean_no_filter(self):
        assert SearchLanguages.parse(None) is None
        assert SearchLanguages.parse("auto") is None
        assert SearchLanguages.parse("") is None

    def test_a_list_is_split_and_ordered(self):
        assert SearchLanguages.parse("te, en") == ["en", "te"]
        assert SearchLanguages.parse(["te", "en"]) == ["en", "te"]

    def test_an_unknown_language_is_refused(self):
        with pytest.raises(SearchLanguageError):
            SearchLanguages.parse("xx")


class TestFilter:
    def test_without_a_filter_everything_is_returned(self, storage, pages):
        found = Search.indexed_content(storage, "invoice", engine="like")

        assert _names(found) == ["both", "english", "old", "telugu"]

    def test_english_keeps_english_pages_and_those_with_no_language(self, storage, pages):
        found = Search.indexed_content(storage, "invoice", engine="like", languages="en")

        assert _names(found) == ["both", "english", "old"]

    def test_telugu_keeps_only_pages_read_in_telugu(self, storage, pages):
        found = Search.indexed_content(storage, "invoice", engine="like", languages="te")

        assert _names(found) == ["both", "telugu"]

    def test_both_languages_keep_every_page_read_in_either(self, storage, pages):
        found = Search.indexed_content(storage, "invoice", engine="like", languages="en,te")

        assert _names(found) == ["both", "english", "old", "telugu"]

    def test_the_ranked_all_engine_is_filtered_too(self, storage, pages):
        found = Search.indexed_pages(storage, "invoice", languages="te")

        assert sorted(p.file_name.removesuffix(".pdf") for p in found) == ["both", "telugu"]

    def test_the_default_engine_path_is_filtered_too(self, storage, pages):
        found = Search.indexed_content(storage, "invoice", engine="all", languages="te")

        assert _names(found) == ["both", "telugu"]

    def test_files_are_filtered(self, storage, pages):
        found = Search.files(storage, "invoice", engine="like", languages="te")

        assert sorted(f.file_name for f in found) == ["both.pdf", "telugu.pdf"]

    def test_a_duplicate_is_filtered_by_the_pages_of_the_file_it_duplicates(
        self, conn, storage, pages
    ):
        telugu = conn.execute(
            "SELECT id, document_id, source_id FROM document_index WHERE file_path = ?",
            ("/docs/telugu.pdf",),
        ).fetchone()
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, '/docs/telugu-copy.pdf', 'pdf', 'indexed')",
            (telugu["source_id"], telugu["document_id"]),
        )
        conn.commit()

        found = Search.indexed_content(storage, "అమ్మ", engine="like", languages="te")

        assert "telugu-copy" in _names(found)
        assert "telugu-copy" not in _names(
            Search.indexed_content(storage, "అమ్మ", engine="like", languages="en")
        )

    def test_an_unknown_language_is_refused_before_searching(self, storage, pages):
        with pytest.raises(SearchLanguageError):
            Search.indexed_content(storage, "invoice", engine="like", languages="xx")
