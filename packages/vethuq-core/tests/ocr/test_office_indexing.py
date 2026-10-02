import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from office_fixtures import (
    build_doc_streams,
    cell,
    inline_cell,
    paragraph,
    png_bytes,
    ppt_container,
    ppt_text_chars,
    run_paragraph,
    shape,
    sheet_xml,
    slide_xml,
    write_docx,
    write_pptx,
    write_xls,
    write_xlsx,
)
from vethuq_core.ocr import Quick
from vethuq_core.search import Search
from vethuq_core.source import Sources


def _fake_ocr_result(text="image words", score=0.9):
    return [{"rec_texts": [text], "rec_scores": [score]}]


def _row(conn, path):
    return conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(path.resolve()),)
    ).fetchone()


class TestWordIndexing:
    def test_native_docx_is_indexed_searchable_and_never_touches_ocr(
        self, conn: sqlite3.Connection, tmp_path
    ):
        path = write_docx(tmp_path / "memo.docx", paragraph("Quarterly budget review"))
        source = Sources.add(conn, path)

        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            Quick.run(conn, source)
        get_engine.assert_not_called()

        doc = _row(conn, path)
        assert (doc["status"], doc["file_type"]) == ("indexed", "docx")
        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert (page["ocr_text"], page["source"], page["confidence"]) == (
            "Quarterly budget review",
            "native",
            1.0,
        )

        matches = Search.indexed_content(conn, "budget")
        assert [(m.file_name, m.page_number, m.matched) for m in matches] == [
            ("memo.docx", None, "budget")
        ]

        confidence = conn.execute(
            "SELECT page_count, avg_confidence FROM confidence_metrics "
            "WHERE file_type = 'docx' AND process_type = 'native'"
        ).fetchone()
        assert (confidence["page_count"], confidence["avg_confidence"]) == (1, 1.0)
        assert conn.execute(
            "SELECT document_count FROM processing_metrics WHERE file_type = 'docx'"
        ).fetchone()

    @patch("vethuq_core.ocr.Engine.get")
    def test_docx_with_an_embedded_image_is_mixed_and_its_image_text_is_searchable(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("invoice 4711", 0.85)
        mock_get_engine.return_value = engine
        path = write_docx(
            tmp_path / "scan.docx", paragraph("Cover note"), media={"image1.png": png_bytes()}
        )
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = _row(conn, path)
        assert doc["status"] == "indexed"
        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["source"] == "mixed"
        assert page["ocr_text"] == "Cover note\ninvoice 4711"
        assert page["confidence"] == pytest.approx(0.85)
        assert [m.matched for m in Search.indexed_content(conn, "4711")] == ["4711"]

    def test_reindexing_a_changed_docx_replaces_its_page(self, conn, tmp_path):
        path = write_docx(tmp_path / "a.docx", paragraph("first version"))
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        write_docx(path, paragraph("second version, longer"))
        Quick.run(conn, source)

        texts = [r["ocr_text"] for r in conn.execute("SELECT ocr_text FROM office_pages")]
        assert texts == ["second version, longer"]
        assert Search.indexed_content(conn, "first") == []
        assert len(Search.indexed_content(conn, "second")) == 1

    def test_duplicate_docx_reuses_the_original_pages(self, conn, tmp_path):
        original = write_docx(tmp_path / "a.docx", paragraph("shared text"))
        copy = tmp_path / "b.docx"
        copy.write_bytes(original.read_bytes())
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 1
        assert sorted(m.file_name for m in Search.indexed_content(conn, "shared")) == [
            "a.docx",
            "b.docx",
        ]

    def test_corrupt_docx_is_marked_error_without_pages(self, conn, tmp_path):
        path = tmp_path / "bad.docx"
        path.write_bytes(b"definitely not a zip")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = _row(conn, path)
        assert doc["status"] == "error"
        assert "not a valid" in doc["error_message"]
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0

    def test_word_lock_files_are_ignored(self, conn, tmp_path):
        write_docx(tmp_path / "real.docx", paragraph("content"))
        (tmp_path / "~$real.docx").write_bytes(b"\x05lock")
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        paths = [r["file_path"] for r in conn.execute("SELECT file_path FROM document_index")]
        assert [p.rsplit("/", 1)[-1] for p in paths] == ["real.docx"]

    def test_doc_is_indexed_through_the_ole_parser(self, conn, tmp_path):
        word, tables = build_doc_streams()
        path = tmp_path / "legacy.doc"
        path.write_bytes(b"placeholder")
        source = Sources.add(conn, path)

        with patch(
            "vethuq_core.ocr.reader.DocParser.extract", return_value=("Hello Wörld", [])
        ) as extract:
            Quick.run(conn, source)
        extract.assert_called_once()

        doc = _row(conn, path)
        assert (doc["status"], doc["file_type"]) == ("indexed", "doc")
        assert [m.matched for m in Search.indexed_content(conn, "wörld")] == ["Wörld"]
        assert word and tables  # fixtures are exercised in test_office

    def test_removing_the_source_purges_office_pages(self, conn, tmp_path):
        path = write_docx(tmp_path / "a.docx", paragraph("temporary"))
        source = Sources.add(conn, path)
        Quick.run(conn, source)
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 1

        Sources.remove(conn, source.path)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0
        assert Search.indexed_content(conn, "temporary") == []


class TestExcelIndexing:
    def test_xlsx_is_indexed_searchable_and_never_touches_ocr(
        self, conn: sqlite3.Connection, tmp_path
    ):
        path = write_xlsx(
            tmp_path / "ledger.xlsx",
            {"Q3": sheet_xml([[inline_cell("A1", "Invoice"), cell("B1", 4711)]])},
        )
        source = Sources.add(conn, path)

        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            Quick.run(conn, source)
        get_engine.assert_not_called()

        doc = _row(conn, path)
        assert (doc["status"], doc["file_type"]) == ("indexed", "xlsx")
        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert (page["ocr_text"], page["source"], page["confidence"]) == (
            "Q3\nInvoice\t4711",
            "native",
            1.0,
        )
        assert [(m.file_name, m.page_number) for m in Search.indexed_content(conn, "invoice")] == [
            ("ledger.xlsx", None)
        ]
        assert [m.matched for m in Search.indexed_content(conn, "4711")] == ["4711"]
        assert conn.execute(
            "SELECT page_count FROM confidence_metrics "
            "WHERE file_type = 'xlsx' AND process_type = 'native'"
        ).fetchone()
        assert conn.execute(
            "SELECT document_count FROM processing_metrics WHERE file_type = 'xlsx'"
        ).fetchone()

    @patch("vethuq_core.ocr.Engine.get")
    def test_xlsx_with_a_picture_is_mixed_and_its_text_is_searchable(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("receipt 0042", 0.8)
        mock_get_engine.return_value = engine
        path = write_xlsx(
            tmp_path / "scan.xlsx",
            {"S": sheet_xml([[inline_cell("A1", "Expenses")]])},
            media={"image1.png": png_bytes()},
        )
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (_row(conn, path)["id"],)
        ).fetchone()
        assert (page["source"], page["ocr_text"]) == ("mixed", "S\nExpenses\nreceipt 0042")
        assert [m.matched for m in Search.indexed_content(conn, "0042")] == ["0042"]

    def test_xls_is_indexed_through_xlrd(self, conn: sqlite3.Connection, tmp_path):
        path = write_xls(tmp_path / "legacy.xls", {"Stock": [["bolts", 120], ["nuts", 80]]})
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = _row(conn, path)
        assert (doc["status"], doc["file_type"]) == ("indexed", "xls")
        assert [m.matched for m in Search.indexed_content(conn, "nuts")] == ["nuts"]

    def test_corrupt_workbooks_are_marked_error_without_pages(self, conn, tmp_path):
        (tmp_path / "bad.xlsx").write_bytes(b"definitely not a zip")
        (tmp_path / "bad.xls").write_bytes(b"definitely not biff")
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        rows = conn.execute("SELECT status, error_message FROM document_index").fetchall()
        assert [r["status"] for r in rows] == ["error", "error"]
        assert all("not a valid" in r["error_message"] for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0

    def test_excel_lock_files_are_ignored(self, conn, tmp_path):
        write_xlsx(tmp_path / "real.xlsx", {"S": sheet_xml([[inline_cell("A1", "content")]])})
        (tmp_path / "~$real.xlsx").write_bytes(b"\x05lock")
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        paths = [r["file_path"] for r in conn.execute("SELECT file_path FROM document_index")]
        assert [p.rsplit("/", 1)[-1] for p in paths] == ["real.xlsx"]

    def test_duplicate_workbooks_reuse_the_original_pages(self, conn, tmp_path):
        original = write_xlsx(
            tmp_path / "a.xlsx", {"S": sheet_xml([[inline_cell("A1", "shared figures")]])}
        )
        (tmp_path / "b.xlsx").write_bytes(original.read_bytes())
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 1
        assert sorted(m.file_name for m in Search.indexed_content(conn, "figures")) == [
            "a.xlsx",
            "b.xlsx",
        ]

    def test_removing_the_source_purges_excel_pages(self, conn, tmp_path):
        path = write_xlsx(tmp_path / "a.xlsx", {"S": sheet_xml([[inline_cell("A1", "temporary")]])})
        source = Sources.add(conn, path)
        Quick.run(conn, source)
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 1

        Sources.remove(conn, source.path)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0
        assert Search.indexed_content(conn, "temporary") == []


class TestPowerPointIndexing:
    def test_pptx_is_indexed_searchable_and_never_touches_ocr(
        self, conn: sqlite3.Connection, tmp_path
    ):
        path = write_pptx(
            tmp_path / "deck.pptx",
            [
                slide_xml(shape(run_paragraph("Roadmap 2027"), placeholder="title")),
                slide_xml(shape(run_paragraph("Launch plan"))),
            ],
        )
        source = Sources.add(conn, path)

        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            Quick.run(conn, source)
        get_engine.assert_not_called()

        doc = _row(conn, path)
        assert (doc["status"], doc["file_type"]) == ("indexed", "pptx")
        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert (page["ocr_text"], page["source"], page["confidence"]) == (
            "Roadmap 2027\nLaunch plan",
            "native",
            1.0,
        )
        assert [(m.file_name, m.page_number) for m in Search.indexed_content(conn, "roadmap")] == [
            ("deck.pptx", None)
        ]
        assert conn.execute(
            "SELECT page_count FROM confidence_metrics "
            "WHERE file_type = 'pptx' AND process_type = 'native'"
        ).fetchone()
        assert conn.execute(
            "SELECT document_count FROM processing_metrics WHERE file_type = 'pptx'"
        ).fetchone()

    @patch("vethuq_core.ocr.Engine.get")
    def test_pptx_with_a_picture_is_mixed_and_its_text_is_searchable(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("whiteboard 0042", 0.8)
        mock_get_engine.return_value = engine
        path = write_pptx(
            tmp_path / "photo.pptx",
            [slide_xml(shape(run_paragraph("Workshop")))],
            slide_rels={1: [("rId1", "image", "../media/image1.png")]},
            media={"image1.png": png_bytes()},
        )
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (_row(conn, path)["id"],)
        ).fetchone()
        assert (page["source"], page["ocr_text"]) == ("mixed", "Workshop\nwhiteboard 0042")
        assert [m.matched for m in Search.indexed_content(conn, "0042")] == ["0042"]

    def test_ppt_is_indexed_through_its_record_stream(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "legacy.ppt"
        path.write_bytes(b"ole placeholder")
        streams = {
            "PowerPoint Document": ppt_container(0x03EE, ppt_text_chars("Budget forecast\r"))
        }
        source = Sources.add(conn, path)

        class FakeOle:
            def __init__(self, _):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def exists(self, name):
                return name in streams

            def openstream(self, name):
                import io

                return io.BytesIO(streams[name])

        with (
            patch("olefile.isOleFile", return_value=True),
            patch("olefile.OleFileIO", FakeOle),
        ):
            Quick.run(conn, source)

        doc = _row(conn, path)
        assert (doc["status"], doc["file_type"]) == ("indexed", "ppt")
        assert [m.matched for m in Search.indexed_content(conn, "forecast")] == ["forecast"]

    def test_corrupt_presentations_are_marked_error_without_pages(self, conn, tmp_path):
        (tmp_path / "bad.pptx").write_bytes(b"definitely not a zip")
        (tmp_path / "bad.ppt").write_bytes(b"definitely not ole")
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        rows = conn.execute("SELECT status, error_message FROM document_index").fetchall()
        assert [r["status"] for r in rows] == ["error", "error"]
        assert all("not a valid" in r["error_message"] for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0

    def test_powerpoint_lock_files_are_ignored(self, conn, tmp_path):
        write_pptx(tmp_path / "real.pptx", [slide_xml(shape(run_paragraph("content")))])
        (tmp_path / "~$real.pptx").write_bytes(b"\x05lock")
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        paths = [r["file_path"] for r in conn.execute("SELECT file_path FROM document_index")]
        assert [p.rsplit("/", 1)[-1] for p in paths] == ["real.pptx"]

    def test_duplicate_presentations_reuse_the_original_pages(self, conn, tmp_path):
        original = write_pptx(tmp_path / "a.pptx", [slide_xml(shape(run_paragraph("shared deck")))])
        (tmp_path / "b.pptx").write_bytes(original.read_bytes())
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 1
        assert sorted(m.file_name for m in Search.indexed_content(conn, "shared")) == [
            "a.pptx",
            "b.pptx",
        ]

    def test_removing_the_source_purges_powerpoint_pages(self, conn, tmp_path):
        path = write_pptx(tmp_path / "a.pptx", [slide_xml(shape(run_paragraph("temporary")))])
        source = Sources.add(conn, path)
        Quick.run(conn, source)
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 1

        Sources.remove(conn, source.path)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0
        assert Search.indexed_content(conn, "temporary") == []
