"""Native pages carry the language their text is written in (they were not read in one)."""

import pytest
from vethuq_core.ocr.document import Document
from vethuq_core.ocr.page_languages import PageLanguages
from vethuq_core.readers import PageResult

TELUGU = "తెలుగు భాష మధురమైనది"
ENGLISH = "Invoice total due"
MIXED = "Annual Meeting Notice వార్షిక సమావేశ నోటీసు"


def _store(conn, storage, texts, source="native", language=None):
    conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES ('/docs', 'folder', 'indexed', 'x')"
    )
    conn.execute("INSERT INTO documents (created_at) VALUES ('x')")
    document_id = conn.execute(
        "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
        "VALUES (1, 1, '/docs/a.pdf', 'pdf', 'indexed')"
    ).lastrowid
    pages = [PageResult(text=t, confidence=1.0, source=source, language=language) for t in texts]
    Document.store_pages(storage, document_id, "pdf", pages)
    conn.commit()
    return [
        (r["language"], r["ocr_langs"])
        for r in conn.execute(
            "SELECT language, ocr_langs FROM pdf_pages WHERE document_id = ? ORDER BY page_number",
            (document_id,),
        )
    ]


class TestOfText:
    def test_telugu_text_is_telugu(self):
        assert PageLanguages.of_text(TELUGU) == ["te"]

    def test_english_text_is_english(self):
        assert PageLanguages.of_text(ENGLISH) == ["en"]

    def test_mixed_text_lists_the_language_with_most_characters_first(self):
        assert PageLanguages.of_text(MIXED) == ["en", "te"]
        assert PageLanguages.of_text("Hi " + TELUGU) == ["te", "en"]

    def test_digits_and_punctuation_have_no_language(self):
        assert PageLanguages.of_text("2024 - 15,000.00") == []


class TestTag:
    def test_a_native_telugu_page_is_recorded_as_telugu(self, conn, storage):
        assert _store(conn, storage, [TELUGU]) == [("te", "")]

    def test_a_native_mixed_page_records_both_languages(self, conn, storage):
        assert _store(conn, storage, [MIXED]) == [("en", "en,te")]

    def test_pages_are_tagged_one_by_one(self, conn, storage):
        assert _store(conn, storage, [TELUGU, ENGLISH, TELUGU]) == [
            ("te", ""),
            (None, ""),
            ("te", ""),
        ]

    def test_english_pages_are_stored_exactly_as_before(self, conn, storage):
        assert _store(conn, storage, [ENGLISH]) == [(None, "")]

    def test_a_page_with_no_letters_is_left_alone(self, conn, storage):
        assert _store(conn, storage, ["2024 - 15,000.00"]) == [(None, "")]

    @pytest.mark.parametrize(("text", "language"), [(TELUGU, "te"), (ENGLISH, "en")])
    def test_a_scanned_page_keeps_the_language_it_was_read_in(self, conn, storage, text, language):
        assert _store(conn, storage, [text], source="ocr", language=language) == [(language, "")]

    @pytest.mark.parametrize("source", ["native", "mixed"])
    def test_a_mixed_page_keeps_the_language_its_image_regions_were_read_in(
        self, conn, storage, source
    ):
        # The OCR'd regions were read in English; the native text is Telugu.
        assert _store(conn, storage, [TELUGU], source=source, language="en") == [("te", "te,en")]
