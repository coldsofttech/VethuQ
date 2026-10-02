from unittest.mock import MagicMock, patch

import pytest
from office_fixtures import jpg_bytes, png_bytes
from rtf_fixtures import rtf_picture, write_rtf
from vethuq_core.ocr import Quick, Readers, RtfReader
from vethuq_core.ocr.office import RtfParser
from vethuq_core.search import Search
from vethuq_core.source import Sources


def _fake_ocr_result(text="image words", score=0.9):
    return [{"rec_texts": [text], "rec_scores": [score]}]


class TestRtfParser:
    def test_extracts_text_and_decodes_unicode_and_codepage_escapes(self, tmp_path):
        path = write_rtf(tmp_path / "a.rtf", "Caf\\'e9 \\u8364? budget\\par second line")

        text, images = RtfParser.extract(path)

        assert text == "Café € budget\nsecond line"
        assert images == []

    def test_picture_data_is_not_leaked_into_the_text(self, tmp_path):
        png = png_bytes()
        path = write_rtf(tmp_path / "a.rtf", f"before {rtf_picture(png)} after")

        text, images = RtfParser.extract(path)

        assert text == "before after"
        assert images == [png]

    def test_carves_png_and_jpeg_in_order_and_dedupes(self, tmp_path):
        png, jpg = png_bytes(), jpg_bytes()
        body = " ".join(
            [rtf_picture(png), rtf_picture(jpg, "jpegblip", uid=False), rtf_picture(png)]
        )
        path = write_rtf(tmp_path / "a.rtf", body)

        assert RtfParser.extract(path)[1] == [png, jpg]

    def test_skips_unsupported_and_binary_pictures(self, tmp_path):
        body = (
            rtf_picture(b"\x01\x02\x03\x04", "wmetafile8")
            + "{\\pict\\pngblip\\bin4 abcd}"
            + rtf_picture(b"not a png", "pngblip")
        )
        path = write_rtf(tmp_path / "a.rtf", body)

        assert RtfParser.extract(path)[1] == []

    def test_rejects_a_file_that_is_not_rtf(self, tmp_path):
        path = tmp_path / "bad.rtf"
        path.write_bytes(b"plain text, not rtf")

        with pytest.raises(ValueError, match="not a valid .rtf"):
            RtfParser.extract(path)


class TestRtfReader:
    def test_registered_for_rtf_suffix(self, tmp_path):
        path = tmp_path / "a.RTF"
        assert Readers.is_supported(path)
        assert isinstance(Readers.for_path(path), RtfReader)
        assert RtfReader.file_type == "rtf"

    def test_text_only_is_native_and_skips_ocr(self, conn, tmp_path):
        path = write_rtf(tmp_path / "memo.rtf", "Quarterly budget review")

        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            [page] = RtfReader().ocr(conn, path)
        get_engine.assert_not_called()

        assert (page.text, page.source, page.confidence) == (
            "Quarterly budget review",
            "native",
            1.0,
        )


class TestRtfIndexing:
    def test_rtf_is_indexed_and_searchable(self, conn, tmp_path):
        path = write_rtf(tmp_path / "memo.rtf", "Quarterly budget review")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = conn.execute("SELECT * FROM document_index").fetchone()
        assert (doc["status"], doc["file_type"]) == ("indexed", "rtf")
        page = conn.execute(
            "SELECT * FROM office_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert (page["ocr_text"], page["source"]) == ("Quarterly budget review", "native")
        assert [(m.file_name, m.matched) for m in Search.indexed_content(conn, "budget")] == [
            ("memo.rtf", "budget")
        ]
        assert conn.execute(
            "SELECT page_count FROM confidence_metrics "
            "WHERE file_type = 'rtf' AND process_type = 'native'"
        ).fetchone()

    @patch("vethuq_core.ocr.Engine.get")
    def test_embedded_image_text_is_indexed_as_mixed_in_quick_phase_only(
        self, mock_get_engine, conn, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("invoice 4711", 0.85)
        mock_get_engine.return_value = engine
        path = write_rtf(tmp_path / "scan.rtf", f"Cover note {rtf_picture(png_bytes())}")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        page = conn.execute("SELECT * FROM office_pages").fetchone()
        assert page["source"] == "mixed"
        assert page["ocr_text"] == "Cover note\ninvoice 4711"
        assert page["confidence"] == pytest.approx(0.85)
        assert engine.predict.call_count == 1  # one upright pass, no rotated phases
        assert [m.matched for m in Search.indexed_content(conn, "4711")] == ["4711"]

    def test_corrupt_rtf_is_marked_error(self, conn, tmp_path):
        path = tmp_path / "bad.rtf"
        path.write_bytes(b"nope")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = conn.execute("SELECT * FROM document_index").fetchone()
        assert doc["status"] == "error"
        assert conn.execute("SELECT COUNT(*) FROM office_pages").fetchone()[0] == 0
