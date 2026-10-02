import struct
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from office_fixtures import (
    W_NS,
    blip_record,
    build_doc_streams,
    build_xls_stream,
    cell,
    inline_cell,
    jpg_bytes,
    paragraph,
    png_bytes,
    sheet_xml,
    write_docx,
    write_xls,
    write_xlsx,
)
from vethuq_core.ocr import DocReader, DocxReader, Readers, XlsReader, XlsxReader
from vethuq_core.ocr.office import DocParser, DocxParser, Excel, XlsParser, XlsxParser
from vethuq_core.ocr.reader import OfficeReader


def _fake_ocr_result(text="from image", score=0.9):
    return [{"rec_texts": [text], "rec_scores": [score]}]


class TestDocxParser:
    def test_extracts_paragraphs_tabs_breaks_and_tables_in_order(self, tmp_path):
        body = (
            paragraph("First paragraph")
            + f'<w:p xmlns:w="{W_NS}"><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t>'
            + "<w:br/><w:t>c</w:t></w:r></w:p>"
            + "<w:tbl><w:tr><w:tc>"
            + paragraph("cell one")
            + "</w:tc><w:tc>"
            + paragraph("cell two")
            + "</w:tc></w:tr></w:tbl>"
            + paragraph("Last")
        )
        path = write_docx(tmp_path / "a.docx", body)

        text, images = DocxParser.extract(path)

        assert text == "First paragraph\na\tb\nc\ncell one\ncell two\nLast"
        assert images == []

    def test_skips_tracked_deletions_and_alternate_content_fallback(self, tmp_path):
        body = (
            "<w:p><w:r><w:t>kept</w:t></w:r><w:del><w:r><w:delText>gone</w:delText></w:r></w:del></w:p>"
            "<mc:AlternateContent>"
            "<mc:Choice><w:p><w:r><w:t>textbox</w:t></w:r></w:p></mc:Choice>"
            "<mc:Fallback><w:p><w:r><w:t>textbox</w:t></w:r></w:p></mc:Fallback>"
            "</mc:AlternateContent>"
        )
        text, _ = DocxParser.extract(write_docx(tmp_path / "a.docx", body))
        assert text == "kept\ntextbox"

    def test_text_box_paragraphs_are_not_duplicated_into_the_host_paragraph(self, tmp_path):
        body = (
            "<w:p><w:r><w:t>host</w:t></w:r>"
            "<w:r><w:pict><w:txbxContent><w:p><w:r><w:t>boxed</w:t></w:r></w:p></w:txbxContent>"
            "</w:pict></w:r></w:p>"
        )
        text, _ = DocxParser.extract(write_docx(tmp_path / "a.docx", body))
        assert text == "host\nboxed"

    def test_reads_headers_footers_and_footnotes_after_the_body(self, tmp_path):
        def part(text):
            return f'<w:hdr xmlns:w="{W_NS}"><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:hdr>'

        path = write_docx(
            tmp_path / "a.docx",
            paragraph("body"),
            parts={
                "word/header1.xml": part("head"),
                "word/footer1.xml": part("foot"),
                "word/footnotes.xml": part("note"),
            },
        )
        text, _ = DocxParser.extract(path)
        assert text.split("\n")[0] == "body"
        assert set(text.split("\n")) == {"body", "head", "foot", "note"}

    def test_returns_raster_images_in_natural_order_and_dedupes(self, tmp_path):
        png, jpg = png_bytes(), jpg_bytes()
        path = write_docx(
            tmp_path / "a.docx",
            paragraph("x"),
            media={
                "image10.png": jpg,
                "image2.png": png,
                "copy.png": png,
                "drawing.emf": b"not raster",
            },
        )
        _, images = DocxParser.extract(path)
        assert images == [png, jpg]

    def test_rejects_non_word_zip_and_non_zip(self, tmp_path):
        not_word = tmp_path / "x.docx"
        with zipfile.ZipFile(not_word, "w") as package:
            package.writestr("hello.txt", "hi")
        with pytest.raises(ValueError, match="document.xml"):
            DocxParser.extract(not_word)

        garbage = tmp_path / "y.docx"
        garbage.write_bytes(b"this is not a zip")
        with pytest.raises(ValueError, match="not a valid"):
            DocxParser.extract(garbage)


class TestDocParser:
    def test_reads_compressed_and_utf16_pieces(self):
        word, tables = build_doc_streams()
        assert DocParser.text(word, tables.get) == "Hello\nWörld€"

    def test_uses_0table_when_flag_clear(self):
        word, tables = build_doc_streams(table_stream_1=False)
        assert DocParser.text(word, tables.get) == "Hello\nWörld€"

    def test_missing_table_stream_is_an_error(self):
        word, _ = build_doc_streams()
        with pytest.raises(ValueError, match="1Table"):
            DocParser.text(word, lambda _name: None)

    def test_encrypted_and_bad_signature_are_errors(self):
        word, tables = build_doc_streams(encrypted=True)
        with pytest.raises(ValueError, match="password"):
            DocParser.text(word, tables.get)
        with pytest.raises(ValueError, match="signature"):
            DocParser.text(b"\x00" * 64, tables.get)

    def test_word95_text_is_one_contiguous_run(self):
        word = bytearray(0x100)
        struct.pack_into("<HH", word, 0, 0xA5EC, 0x0065)
        body = "Old caf\xe9\rdoc\r".encode("cp1252")
        word[0x80 : 0x80 + len(body)] = body
        struct.pack_into("<II", word, 0x18, 0x80, 0x80 + len(body))
        assert DocParser.text(bytes(word), lambda _n: None) == "Old café\ndoc"

    def test_clean_keeps_field_results_and_converts_marks(self):
        raw = (
            'See \x13 HYPERLINK "http://x" \x14the site\x15 now\r'
            "a\x07b\x07\x07\r"
            "x\x0by\x01\x08\x1fz\x1e!\r\r"
        )
        assert DocParser.clean(raw) == "See the site now\na\tb\nx\nyz-!"

    def test_clean_drops_field_without_a_result_and_handles_nesting(self):
        assert DocParser.clean("a\x13 PAGE \x15b") == "ab"
        assert DocParser.clean("\x13 OUTER \x14\x13 INNER \x14deep\x15\x15!") == "deep!"

    def test_carve_pictures_finds_png_and_jpeg_blips(self):
        png, jpg = png_bytes(), jpg_bytes()
        stream = (
            b"\x00\xf0\x1e\xf0 junk that is not a record"
            + blip_record(png, png=True)
            + b"\x00" * 7
            + blip_record(jpg, png=False, two_uids=True)
            + b"tail"
        )
        assert DocParser.carve_pictures(stream) == [png, jpg]

    def test_carve_pictures_ignores_records_with_bad_length_or_signature(self):
        bad_len = struct.pack("<HHI", 0x6E0 << 4, 0xF01E, 10_000) + b"\x00" * 40
        bad_sig = struct.pack("<HHI", 0x46A << 4, 0xF01D, 40) + b"\x11" * 17 + b"nope" * 5
        assert DocParser.carve_pictures(bad_len + bad_sig) == []

    def test_extract_reads_streams_through_olefile(self, tmp_path):
        word, tables = build_doc_streams()
        png = png_bytes()
        streams = {"WordDocument": word, "Data": blip_record(png, png=True), **tables}

        class FakeOle:
            def __init__(self, _path):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def exists(self, name):
                return name in streams

            def openstream(self, name):
                return MagicMock(read=lambda: streams[name])

        path = tmp_path / "a.doc"
        path.write_bytes(b"x")
        with (
            patch("olefile.isOleFile", return_value=True),
            patch("olefile.OleFileIO", FakeOle),
        ):
            text, images = DocParser.extract(path)

        assert text == "Hello\nWörld€"
        assert images == [png]

    def test_extract_rejects_a_non_ole_file(self, tmp_path):
        path = tmp_path / "a.doc"
        path.write_bytes(b"plain text, not OLE")
        with pytest.raises(ValueError, match="OLE"):
            DocParser.extract(path)


class TestExcelValues:
    @pytest.mark.parametrize(
        ("raw", "shown"),
        [("42", "42"), ("42.0", "42"), ("0.1", "0.1"), ("0.30000000000000004", "0.3"),
         ("1E-3", "0.001"), ("-7", "-7"), ("text", "text")],
    )  # fmt: skip
    def test_number_matches_general_format(self, raw, shown):
        assert Excel.number(raw) == shown

    @pytest.mark.parametrize(
        ("serial", "date1904", "shown"),
        [(45000, False, "2023-03-15"), (45000.5, False, "2023-03-15 12:00:00"),
         (0.75, False, "18:00:00"), (61, False, "1900-03-01"), (1, False, "1900-01-01"),
         (1461, True, "1908-01-01"), (0.25, True, "06:00:00"),
         (-3, False, "-3"), (1e12, False, "1000000000000")],
    )  # fmt: skip
    def test_date_serials(self, serial, date1904, shown):
        assert Excel.date(serial, date1904=date1904) == shown

    @pytest.mark.parametrize(
        ("format_id", "code", "is_date"),
        [(14, None, True), (22, None, True), (0, None, False), (9, None, False),
         (164, "yyyy-mm-dd hh:mm", True), (165, '0" days"', False), (166, "[Red]0.00", False),
         (167, "General", False), (168, "dd/mm/yy;@", True), (169, "0.00E+00", False)],
    )  # fmt: skip
    def test_is_date_format(self, format_id, code, is_date):
        assert Excel.is_date_format(format_id, code) is is_date


class TestXlsxParser:
    def test_reads_sheets_in_workbook_order_with_names_rows_and_cells(self, tmp_path):
        path = write_xlsx(
            tmp_path / "a.xlsx",
            {
                "Budget": sheet_xml(
                    [
                        [cell("A1", 0, kind="s"), cell("B1", 1, kind="s")],
                        [cell("A2", 2, kind="s"), cell("B2", 1250.5)],
                        [],
                        [cell("B4", 7)],
                    ]
                ),
                "Notes": sheet_xml([[inline_cell("A1", "inline words")]]),
                "Blank": sheet_xml([[]]),
            },
            shared=("Item", "Cost", "Coffee"),
        )

        text, images = XlsxParser.extract(path)

        assert text == "Budget\nItem\tCost\nCoffee\t1250.5\n7\nNotes\ninline words"
        assert images == []

    def test_cell_kinds_booleans_errors_formula_results_and_empty_values(self, tmp_path):
        row = [
            cell("A1", 1, kind="b"),
            cell("B1", 0, kind="b"),
            cell("C1", "#N/A", kind="e"),
            cell("D1", "formula text", kind="str"),
            cell("E1", 99, kind="s"),  # out of range shared string index
            '<c r="F1"><f>SUM(A1:A2)</f></c>',  # a formula nothing has calculated
            cell("G1", "2024-02-29T00:00:00Z", kind="d"),
        ]
        path = write_xlsx(tmp_path / "a.xlsx", {"S": sheet_xml([row])})

        text, _ = XlsxParser.extract(path)

        assert text == "S\nTRUE\tFALSE\tformula text\t2024-02-29T00:00:00Z"

    def test_dates_are_recognised_through_cell_styles(self, tmp_path):
        row = [
            cell("A1", 45000, style=1),  # built-in date
            cell("B1", 45000.75, style=2),  # custom date-time
            cell("C1", 45000, style=3),  # "0 days" is a number, not a date
            cell("D1", 45000),
        ]
        path = write_xlsx(tmp_path / "a.xlsx", {"S": sheet_xml([row])})

        text, _ = XlsxParser.extract(path)

        assert text == "S\n2023-03-15\t2023-03-15 18:00:00\t45000\t45000"

    def test_1904_date_system_is_honoured(self, tmp_path):
        path = write_xlsx(
            tmp_path / "a.xlsx", {"S": sheet_xml([[cell("A1", 1461, style=1)]])}, date1904=True
        )
        assert XlsxParser.extract(path)[0] == "S\n1908-01-01"

    def test_rich_text_keeps_runs_and_drops_phonetic_hints(self, tmp_path):
        rich = (
            "<si><r><t>Hel</t></r><r><rPr/><t>lo</t></r>"
            "<rPh sb='0' eb='1'><t>ハロー</t></rPh><phoneticPr fontId='1'/></si>"
        )
        path = write_xlsx(
            tmp_path / "a.xlsx",
            {"S": sheet_xml([[cell("A1", 0, kind="s")]])},
            shared=(rich,),
        )
        assert XlsxParser.extract(path)[0] == "S\nHello"

    def test_strict_namespace_and_missing_relationships_are_tolerated(self, tmp_path):
        strict = "http://purl.oclc.org/ooxml/spreadsheetml/main"
        path = write_xlsx(
            tmp_path / "a.xlsx",
            {"Ignored": sheet_xml([[inline_cell("A1", "found")]], ns=strict)},
            rels=False,
        )
        # With no relationships the sheets are read in part order and numbered.
        assert XlsxParser.extract(path)[0] == "Sheet1\nfound"

    def test_comments_and_text_boxes_follow_the_sheets(self, tmp_path):
        comments = (
            '<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<commentList><comment ref='A1'><text><r><t>check  this</t></r></text></comment>"
            "</commentList></comments>"
        )
        drawing = (
            '<xdr:wsDr xmlns:xdr="x" xmlns:a="a"><xdr:sp><xdr:txBody><a:p><a:r><a:t>boxed</a:t>'
            "</a:r></a:p></xdr:txBody></xdr:sp></xdr:wsDr>"
        )
        path = write_xlsx(
            tmp_path / "a.xlsx",
            {"S": sheet_xml([[inline_cell("A1", "cell")]])},
            parts={"xl/comments1.xml": comments, "xl/drawings/drawing1.xml": drawing},
        )
        assert XlsxParser.extract(path)[0] == "S\ncell\ncheck this\nboxed"

    def test_returns_images_in_natural_order_and_dedupes(self, tmp_path):
        first, second = png_bytes(), jpg_bytes()
        path = write_xlsx(
            tmp_path / "a.xlsx",
            {"S": sheet_xml([[inline_cell("A1", "x")]])},
            media={"image10.png": second, "image2.png": first, "dup.png": first, "n.emf": b"vec"},
        )
        _, images = XlsxParser.extract(path)
        assert images == [first, second]

    def test_rejects_non_workbooks(self, tmp_path):
        path = tmp_path / "a.xlsx"
        path.write_bytes(b"plain text")
        with pytest.raises(ValueError, match="not a valid .xlsx"):
            XlsxParser.extract(path)

        docx = write_docx(tmp_path / "b.xlsx", paragraph("hi"))
        with pytest.raises(ValueError, match="xl/workbook.xml is missing"):
            XlsxParser.extract(docx)

    def test_an_ole_file_is_reported_as_protected_or_old(self, tmp_path):
        path = tmp_path / "locked.xlsx"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        with pytest.raises(ValueError, match="password-protected"):
            XlsxParser.extract(path)

    def test_oversized_parts_are_refused(self, tmp_path, monkeypatch):
        path = write_xlsx(tmp_path / "a.xlsx", {"S": sheet_xml([[inline_cell("A1", "x")]])})
        monkeypatch.setattr(XlsxParser, "MAX_XML_PART_BYTES", 10)
        with pytest.raises(ValueError, match="too large"):
            XlsxParser.extract(path)


class TestXlsParser:
    def test_reads_sheets_rows_and_typed_cells(self, tmp_path):
        path = write_xls(
            tmp_path / "a.xls",
            {
                "Data": [
                    ["Name", "Qty", None, True, False],
                    ["wörld €", 3, 4.5, ("date", 45000), ("date", 45000.5)],
                ],
                "Empty": [[]],
                "More": [["tail"]],
            },
        )

        assert XlsParser.text(path) == (
            "Data\nName\tQty\tTRUE\tFALSE\nwörld €\t3\t4.5\t2023-03-15\t2023-03-15 12:00:00"
            "\nMore\ntail"
        )

    def test_1904_workbooks_use_their_own_epoch(self, tmp_path):
        path = write_xls(tmp_path / "a.xls", {"S": [[("date", 1461)]]}, date1904=True)
        assert XlsParser.text(path) == "S\n1908-01-01"

    def test_garbage_and_html_posing_as_xls_are_rejected(self, tmp_path):
        path = tmp_path / "a.xls"
        path.write_bytes(b"<html><table><tr><td>not excel</td></tr></table></html>")
        with pytest.raises(ValueError, match="not a valid .xls"):
            XlsParser.text(path)

    def test_truncated_workbook_is_reported_as_corrupt(self, tmp_path):
        path = tmp_path / "a.xls"
        path.write_bytes(build_xls_stream({"S": [["text"]]})[:60])
        with pytest.raises(ValueError, match="xls"):
            XlsParser.text(path)

    def test_encrypted_workbooks_are_reported(self, tmp_path):
        import xlrd

        path = write_xls(tmp_path / "a.xls", {"S": [["x"]]})
        with (
            patch("xlrd.open_workbook", side_effect=xlrd.XLRDError("Workbook is encrypted")),
            pytest.raises(ValueError, match="password-protected"),
        ):
            XlsParser.text(path)

    def test_drawing_group_rejoins_continue_records(self):
        png = png_bytes(300, 300)  # large enough to straddle a CONTINUE boundary
        assert len(png) > 0
        group = b"\x00" * 8200 + blip_record(png, png=True) + b"\x00" * 30

        stream = build_xls_stream({"S": [["x"]]}, drawing_group=group)

        assert XlsParser.drawing_group(stream) == group
        assert DocParser.carve_pictures(XlsParser.drawing_group(stream)) == [png]

    def test_drawing_group_ignores_other_records_and_later_substreams(self):
        stream = build_xls_stream({"S": [["x"]]})
        assert XlsParser.drawing_group(stream) == b""

    def test_extract_carves_pictures_through_olefile(self, tmp_path):
        png = png_bytes()
        stream = build_xls_stream(
            {"S": [["x"]]}, drawing_group=b"\x00" * 5 + blip_record(png, png=True)
        )
        path = write_xls(tmp_path / "a.xls", {"S": [["x"]]})

        class FakeOle:
            def __init__(self, _):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def exists(self, name):
                return name == "Workbook"

            def openstream(self, name):
                import io

                return io.BytesIO(stream)

        with (
            patch("olefile.isOleFile", return_value=True),
            patch("olefile.OleFileIO", FakeOle),
        ):
            text, images = XlsParser.extract(path)

        assert text == "S\nx"
        assert images == [png]

    def test_a_picture_failure_never_loses_the_text(self, tmp_path):
        path = write_xls(tmp_path / "a.xls", {"S": [["kept"]]})
        with patch("olefile.isOleFile", side_effect=RuntimeError("boom")):
            assert XlsParser.extract(path) == ("S\nkept", [])


class TestOfficeReader:
    def test_registry_maps_office_suffixes_and_skips_lock_files(self, tmp_path):
        assert isinstance(Readers.for_path(tmp_path / "a.DOCX"), DocxReader)
        assert isinstance(Readers.for_path(tmp_path / "a.doc"), DocReader)
        assert isinstance(Readers.for_path(tmp_path / "a.XLSX"), XlsxReader)
        assert isinstance(Readers.for_path(tmp_path / "a.xls"), XlsReader)
        assert Readers.is_supported(tmp_path / "a.docx")
        assert not Readers.is_supported(tmp_path / "~$a.docx")
        assert not Readers.is_supported(tmp_path / "~$a.xlsx")
        assert {"doc", "docx", "xls", "xlsx"} <= set(Readers.new_file_type_counts())

        names = ("a.docx", "b.doc", "c.xlsx", "d.xls", "~$a.docx", "~$c.xlsx", "e.txt")
        for name in names:
            (tmp_path / name).write_bytes(b"x")
        assert sorted(p.name for p in Readers.iter_files(tmp_path)) == [
            "a.docx",
            "b.doc",
            "c.xlsx",
            "d.xls",
        ]

    def test_native_only_page_needs_no_ocr(self, conn):
        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            page = OfficeReader.build_page(conn, "  plain text  ", [])
        get_engine.assert_not_called()
        assert (page.text, page.confidence, page.source) == ("plain text", 1.0, "native")
        assert page.ocr_engine is None

    @patch("vethuq_core.ocr.Engine.get")
    def test_images_with_text_make_the_page_mixed(self, mock_get_engine, conn):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("from image", 0.8)
        mock_get_engine.return_value = engine

        page = OfficeReader.build_page(conn, "native", [png_bytes(), b"not an image"])

        assert page.text == "native\nfrom image"
        assert page.source == "mixed"
        assert page.confidence == pytest.approx(0.8)
        assert page.ocr_engine is not None
        assert engine.predict.call_count == 1  # the undecodable one is skipped

    @patch("vethuq_core.ocr.Engine.get")
    def test_image_only_document_is_ocr_and_tiny_images_are_skipped(self, mock_get_engine, conn):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("scanned", 0.7)
        mock_get_engine.return_value = engine

        page = OfficeReader.build_page(conn, "", [png_bytes(10, 10), png_bytes()])

        assert (page.text, page.source) == ("scanned", "ocr")
        assert engine.predict.call_count == 1

    @patch("vethuq_core.ocr.Engine.get")
    def test_images_without_text_leave_a_native_page(self, mock_get_engine, conn):
        engine = MagicMock()
        engine.predict.return_value = [{"rec_texts": [], "rec_scores": []}]
        mock_get_engine.return_value = engine

        page = OfficeReader.build_page(conn, "just text", [png_bytes()])

        assert (page.text, page.source, page.confidence) == ("just text", "native", 1.0)

    @patch("vethuq_core.ocr.Engine.get")
    def test_a_failing_image_does_not_lose_the_text(self, mock_get_engine, conn):
        engine = MagicMock()
        engine.predict.side_effect = RuntimeError("boom")
        mock_get_engine.return_value = engine

        page = OfficeReader.build_page(conn, "keep me", [png_bytes()])

        assert (page.text, page.source) == ("keep me", "native")
