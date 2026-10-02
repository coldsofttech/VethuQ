import codecs
import sqlite3
from unittest.mock import patch

import pytest
from vethuq_core.ocr import Quick, Readers, TxtReader
from vethuq_core.search import Search
from vethuq_core.source import Sources


class TestTxtReaderDecode:
    def test_plain_utf8(self):
        text, encoding, confidence = TxtReader.decode("héllo wörld".encode())

        assert (text, encoding, confidence) == ("héllo wörld", "utf-8", 1.0)

    def test_ascii_is_read_as_utf8(self):
        assert TxtReader.decode(b"just ascii")[1:] == ("utf-8", 1.0)

    def test_utf8_bom_is_consumed(self):
        text, encoding, confidence = TxtReader.decode(codecs.BOM_UTF8 + b"hello")

        assert (text, encoding, confidence) == ("hello", "utf-8-sig", 1.0)

    @pytest.mark.parametrize(
        "data",
        [
            codecs.BOM_UTF16_LE + "wide text ✓".encode("utf-16-le"),
            codecs.BOM_UTF16_BE + "wide text ✓".encode("utf-16-be"),
            codecs.BOM_UTF32_LE + "wide text ✓".encode("utf-32-le"),
        ],
    )
    def test_bom_marked_wide_encodings(self, data):
        text, _, confidence = TxtReader.decode(data)

        assert text == "wide text ✓"
        assert confidence == 1.0

    def test_legacy_single_byte_encoding_is_detected(self):
        sentence = "Привет, как дела? Это простой текст в старой кодировке для проверки."
        data = sentence.encode("cp1251")

        text, encoding, confidence = TxtReader.decode(data)

        assert text == sentence
        assert encoding != "utf-8"
        assert 0.0 < confidence <= 1.0

    def test_binary_data_is_rejected(self):
        with pytest.raises(ValueError, match="not plain text"):
            TxtReader.decode(bytes(range(256)) * 4)

    def test_undetectable_text_falls_back_with_reduced_confidence(self):
        with patch("charset_normalizer.from_bytes") as from_bytes:
            from_bytes.return_value.best.return_value = None
            text, encoding, confidence = TxtReader.decode(b"caf\xe9 maybe")

        assert text == "café maybe"
        assert encoding == TxtReader.FALLBACK_ENCODING
        assert confidence == TxtReader.FALLBACK_CONFIDENCE


class TestTxtReaderFile:
    def test_read_file_returns_single_native_page(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("  line one\nline two\n\n", encoding="utf-8")

        page = TxtReader().ocr(None, path)[0:1][0]  # type: ignore[arg-type]

        assert page.text == "line one\nline two"
        assert page.source == "native"
        assert page.confidence == 1.0
        assert page.encoding == "utf-8"
        assert page.ocr_engine is None

    def test_empty_file_yields_empty_page(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_bytes(b"")

        assert TxtReader.read_file(path).text == ""

    def test_registered_by_suffix_case_insensitively(self, tmp_path):
        assert Readers.is_supported(tmp_path / "A.TXT")
        assert Readers.for_path(tmp_path / "a.txt").file_type == "txt"
        assert Readers.new_file_type_counts()["txt"] == 0


class TestTxtIndexing:
    @patch("vethuq_core.ocr.Engine.get")
    def test_run_indexes_and_searches_txt_without_ocr_engine(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        path = tmp_path / "notes.txt"
        path.write_text("Quarterly budget review: total amount due is 1200.", encoding="utf-8")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        mock_get_engine.assert_not_called()
        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(path.resolve()),)
        ).fetchone()
        assert doc["status"] == "indexed"
        assert doc["file_type"] == "txt"
        page = conn.execute(
            "SELECT * FROM text_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["source"] == "native"
        assert page["encoding"] == "utf-8"

        confidence = conn.execute(
            "SELECT page_count, avg_confidence FROM confidence_metrics "
            "WHERE file_type = 'txt' AND process_type = 'native'"
        ).fetchone()
        assert (confidence["page_count"], confidence["avg_confidence"]) == (1, 1.0)

        matches = Search.indexed_content(conn, "AMOUNT due")
        assert [(m.file_name, m.page_number) for m in matches] == [("notes.txt", None)]

    def test_reindexing_replaces_text(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("first version", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        path.write_text("second edition, longer", encoding="utf-8")
        Quick.run(conn, source, only_new_files=True)

        assert [r["ocr_text"] for r in conn.execute("SELECT ocr_text FROM text_pages")] == [
            "second edition, longer"
        ]

    def test_binary_file_named_txt_is_marked_error(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "fake.txt"
        path.write_bytes(bytes(range(256)) * 4)
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = conn.execute("SELECT status, error_message FROM document_index").fetchone()
        assert doc["status"] == "error"
        assert "not plain text" in doc["error_message"]

    def test_removing_source_deletes_text_pages(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("some searchable words", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        Sources.remove(conn, source.id)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM text_pages").fetchone()[0] == 0
