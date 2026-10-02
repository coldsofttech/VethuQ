import codecs
import shutil
import sqlite3
from unittest.mock import patch

import pytest
from vethuq_core.ocr import CsvReader, Quick, Readers
from vethuq_core.search import Search
from vethuq_core.source import Sources


class TestCsvReaderDecode:
    def test_plain_utf8(self):
        assert CsvReader.decode("héllo,wörld".encode()) == ("héllo,wörld", "utf-8", 1.0)

    def test_utf8_bom_is_consumed(self):
        text, encoding, confidence = CsvReader.decode(codecs.BOM_UTF8 + b"a,b")

        assert (text, encoding, confidence) == ("a,b", "utf-8-sig", 1.0)

    @pytest.mark.parametrize(
        "data",
        [
            codecs.BOM_UTF16_LE + "a,é,✓".encode("utf-16-le"),
            codecs.BOM_UTF16_BE + "a,é,✓".encode("utf-16-be"),
            codecs.BOM_UTF32_LE + "a,é,✓".encode("utf-32-le"),
            codecs.BOM_UTF32_BE + "a,é,✓".encode("utf-32-be"),
        ],
    )
    def test_bom_marked_wide_encodings(self, data):
        text, _, confidence = CsvReader.decode(data)

        assert text == "a,é,✓"
        assert confidence == 1.0

    def test_legacy_single_byte_encoding_is_detected(self):
        sentence = "Привет,как дела?,Это простой текст в старой кодировке для проверки."
        text, encoding, confidence = CsvReader.decode(sentence.encode("cp1251"))

        assert text == sentence
        assert encoding != "utf-8"
        assert 0.0 < confidence <= 1.0

    def test_binary_data_is_rejected(self):
        with pytest.raises(ValueError, match="not a CSV"):
            CsvReader.decode(bytes(range(256)) * 4)

    def test_undetectable_text_falls_back_with_reduced_confidence(self):
        with patch("charset_normalizer.from_bytes") as from_bytes:
            from_bytes.return_value.best.return_value = None
            text, encoding, confidence = CsvReader.decode(b"caf\xe9,maybe")

        assert text == "café,maybe"
        assert encoding == CsvReader.FALLBACK_ENCODING
        assert confidence == CsvReader.FALLBACK_CONFIDENCE


class TestCsvReaderFlatten:
    def test_rows_become_lines_of_pipe_joined_cells(self):
        text, delimiter, rows, columns = CsvReader.flatten("name,city\nAda,London\nGrace,NYC\n")

        assert text == "name | city\nAda | London\nGrace | NYC"
        assert (delimiter, rows, columns) == (",", 3, 2)

    @pytest.mark.parametrize("delimiter", [";", "\t", "|"])
    def test_other_delimiters_are_sniffed(self, delimiter):
        data = delimiter.join(["id", "name", "score"]) + "\n"
        data += delimiter.join(["1", "Ada", "9,5"]) + "\n"
        data += delimiter.join(["2", "Grace", "8,25"]) + "\n"

        text, found, rows, columns = CsvReader.flatten(data)

        assert found == delimiter
        assert text.splitlines()[1] == "1 | Ada | 9,5"
        assert (rows, columns) == (3, 3)

    def test_quoted_cells_keep_embedded_delimiters_and_collapse_newlines(self):
        text, _, rows, columns = CsvReader.flatten(
            'id,note\n1,"hello, world"\n2,"line one\nline two"\n'
        )

        assert text.splitlines() == ["id | note", "1 | hello, world", "2 | line one line two"]
        assert (rows, columns) == (3, 2)

    def test_blank_rows_and_empty_cells_are_dropped_but_width_is_kept(self):
        text, _, rows, columns = CsvReader.flatten("a,,c\n\n,,\nd,e,f,g\n")

        assert text == "a | c\nd | e | f | g"
        assert (rows, columns) == (2, 4)

    def test_single_column_file_falls_back_to_comma(self):
        text, delimiter, rows, columns = CsvReader.flatten("alpha\nbeta\ngamma\n")

        assert (text, delimiter, rows, columns) == ("alpha\nbeta\ngamma", ",", 3, 1)

    def test_empty_input(self):
        assert CsvReader.flatten("") == ("", ",", 0, 0)

    def test_cell_over_default_csv_field_limit_is_read(self):
        big = "x" * 200_000

        text, _, rows, _ = CsvReader.flatten(f"id,blob\n1,{big}\n")

        assert text.splitlines()[1] == f"1 | {big}"
        assert rows == 2

    def test_sniffing_ignores_a_trailing_partial_row_in_a_large_file(self):
        row = "alpha;beta;gamma\n"
        data = row * (CsvReader.SNIFF_SAMPLE_CHARS // len(row) + 10)

        assert CsvReader.flatten(data)[1] == ";"


class TestCsvReaderFile:
    def test_read_file_returns_single_native_page_with_structure(self, tmp_path):
        path = tmp_path / "people.csv"
        path.write_text("name;age\nAda;36\n", encoding="utf-8")

        (page,) = CsvReader().ocr(None, path)

        assert page.text == "name | age\nAda | 36"
        assert page.source == "native"
        assert page.confidence == 1.0
        assert page.ocr_engine is None
        assert (page.encoding, page.delimiter, page.row_count, page.column_count) == (
            "utf-8",
            ";",
            2,
            2,
        )

    def test_empty_file_yields_empty_page(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_bytes(b"")

        page = CsvReader.read_file(path)

        assert (page.text, page.row_count, page.column_count) == ("", 0, 0)

    def test_registered_by_suffix_case_insensitively(self, tmp_path):
        assert Readers.is_supported(tmp_path / "DATA.CSV")
        assert Readers.for_path(tmp_path / "data.csv").file_type == "csv"
        assert Readers.new_file_type_counts()["csv"] == 0


class TestCsvIndexing:
    @patch("vethuq_core.ocr.Engine.get")
    def test_run_indexes_and_searches_csv_without_ocr_engine(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        path = tmp_path / "invoices.csv"
        path.write_text("id,customer,amount\n1,Acme Corp,1200\n2,Globex,87\n", encoding="utf-8")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        mock_get_engine.assert_not_called()
        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(path.resolve()),)
        ).fetchone()
        assert (doc["status"], doc["file_type"]) == ("indexed", "csv")
        page = conn.execute(
            "SELECT * FROM csv_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert (page["source"], page["encoding"], page["delimiter"]) == ("native", "utf-8", ",")
        assert (page["row_count"], page["column_count"]) == (3, 3)

        confidence = conn.execute(
            "SELECT page_count, avg_confidence FROM confidence_metrics "
            "WHERE file_type = 'csv' AND process_type = 'native'"
        ).fetchone()
        assert (confidence["page_count"], confidence["avg_confidence"]) == (1, 1.0)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM processing_metrics WHERE file_type = 'csv'"
            ).fetchone()[0]
            == 1
        )

        matches = Search.indexed_content(conn, "acme CORP")
        assert [(m.file_name, m.page_number) for m in matches] == [("invoices.csv", None)]
        assert Search.indexed_content(conn, "no such customer") == []

    def test_reindexing_replaces_text(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        path.write_text("a,b\nfirst,second edition\n", encoding="utf-8")
        Quick.run(conn, source)

        assert [r["ocr_text"] for r in conn.execute("SELECT ocr_text FROM csv_pages")] == [
            "a | b\nfirst | second edition"
        ]
        assert Search.indexed_content(conn, "1 | 2") == []

    def test_binary_file_named_csv_is_marked_error(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "fake.csv"
        path.write_bytes(bytes(range(256)) * 4)
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = conn.execute("SELECT status, error_message FROM document_index").fetchone()
        assert doc["status"] == "error"
        assert "not a CSV" in doc["error_message"]

    def test_duplicate_csv_surfaces_as_its_own_search_result(
        self, conn: sqlite3.Connection, tmp_path
    ):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "original.csv").write_text("sku,qty\nWIDGET-9,4\n", encoding="utf-8")
        shutil.copy(folder / "original.csv", folder / "copy.csv")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)

        assert conn.execute("SELECT COUNT(*) FROM csv_pages").fetchone()[0] == 1
        found = {m.file_name for m in Search.indexed_content(conn, "widget-9")}
        assert found == {"original.csv", "copy.csv"}

    def test_removing_source_deletes_csv_pages(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "data.csv"
        path.write_text("a,b\nsearchable,words\n", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        Sources.remove(conn, source.id)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM csv_pages").fetchone()[0] == 0
