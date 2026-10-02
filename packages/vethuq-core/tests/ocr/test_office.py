import struct
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from office_fixtures import (
    W_NS,
    blip_record,
    build_doc_streams,
    jpg_bytes,
    paragraph,
    png_bytes,
    write_docx,
)
from vethuq_core.ocr import DocReader, DocxReader, Readers
from vethuq_core.ocr.office import DocParser, DocxParser
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


class TestOfficeReader:
    def test_registry_maps_word_suffixes_and_skips_lock_files(self, tmp_path):
        assert isinstance(Readers.for_path(tmp_path / "a.DOCX"), DocxReader)
        assert isinstance(Readers.for_path(tmp_path / "a.doc"), DocReader)
        assert Readers.is_supported(tmp_path / "a.docx")
        assert not Readers.is_supported(tmp_path / "~$a.docx")
        assert {"doc", "docx"} <= set(Readers.new_file_type_counts())

        for name in ("a.docx", "b.doc", "~$a.docx", "c.txt"):
            (tmp_path / name).write_bytes(b"x")
        assert sorted(p.name for p in Readers.iter_files(tmp_path)) == ["a.docx", "b.doc"]

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
