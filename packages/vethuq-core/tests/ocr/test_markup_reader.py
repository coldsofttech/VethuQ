import codecs
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.ocr import HtmlReader, PageResult, Quick, Readers, XmlReader
from vethuq_core.ocr.markup import Markup
from vethuq_core.search import Search
from vethuq_core.source import Sources

HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Quarterly Report</title>
<meta name="description" content="Budget overview for Q3">
<style>.hidden { color: red }</style>
<script>var secret = "do not index";</script>
</head>
<body>
<!-- internal note -->
<h1>Budget</h1>
<p>Total <b>amount</b> due is <i>1200</i>.<br>Pay by Friday.</p>
<img src="chart.png" alt="Revenue chart">
<table><tr><th>Item</th><td>Laptop</td></tr></table>
</body></html>"""

XML = """<?xml version="1.0" encoding="utf-8"?>
<catalog xmlns:x="urn:x">
  <book id="7" x:lang="en"><title>Dune</title><author>Herbert</author></book>
  <note>mixed <b>inline</b> tail</note>
  <!-- a comment -->
  <empty/>
</catalog>"""


class TestMarkupDecode:
    def test_utf8(self):
        decoded = Markup.decode("héllo".encode(), is_html=True)

        assert (decoded.text, decoded.encoding, decoded.confidence) == ("héllo", "utf-8", 1.0)

    def test_meta_charset_is_honoured(self):
        data = '<meta charset="windows-1251"><p>Привет</p>'.encode("cp1251")

        decoded = Markup.decode(data, is_html=True)

        assert "Привет" in decoded.text
        assert decoded.confidence == 1.0

    def test_xml_declaration_is_honoured(self):
        data = '<?xml version="1.0" encoding="iso-8859-1"?><a>café</a>'.encode("latin-1")

        decoded = Markup.decode(data, is_html=False)

        assert "café" in decoded.text

    def test_utf16_bom(self):
        data = codecs.BOM_UTF16_LE + "<p>wide ✓</p>".encode("utf-16-le")

        assert "wide ✓" in Markup.decode(data, is_html=True).text

    def test_binary_data_is_rejected(self):
        with pytest.raises(ValueError, match="binary|decoded"):
            Markup.decode(b"\x00\x01\x02\x03" * 64, is_html=True)


class TestHtmlText:
    def test_visible_text_only(self):
        text = Markup.html_text(HTML)[0]

        assert "do not index" not in text
        assert "color: red" not in text
        assert "internal note" not in text
        assert "<" not in text

    def test_inline_markup_does_not_split_phrases(self):
        assert "Total amount due is 1200." in Markup.html_text(HTML)[0]

    def test_blocks_and_breaks_become_lines(self):
        lines = Markup.html_text(HTML)[0].splitlines()

        assert "Budget" in lines
        assert "Pay by Friday." in lines

    def test_title_meta_and_alt_text_are_indexed(self):
        text = Markup.html_text(HTML)[0]

        assert "Quarterly Report" in text
        assert "Budget overview for Q3" in text
        assert "Revenue chart" in text

    def test_table_cells_stay_separated(self):
        assert "Item Laptop" in Markup.html_text(HTML)[0]

    def test_fragment_and_malformed_html(self):
        assert Markup.html_text("<p>unclosed <b>bold")[0].strip() == "unclosed bold"

    def test_image_sources_are_returned_in_order(self):
        _, sources = Markup.html_text(
            '<img src="a.png"><img alt="no src"><img src=" b.jpg "><img src="">'
        )

        assert sources == ["a.png", "b.jpg"]

    def test_empty(self):
        assert Markup.html_text("") == ("", [])


class TestHtmlImages:
    @staticmethod
    def _ocr(text="TEXT FROM IMAGE", confidence=0.9):
        return patch(
            "vethuq_core.ocr.ImageReader.ocr_file",
            return_value=PageResult(text=text, confidence=confidence, source="ocr"),
        )

    @pytest.mark.parametrize(
        "source",
        [
            "http://example.com/a.png",
            "https://example.com/a.png",
            "//cdn.example.com/a.png",
            "data:image/png;base64,AAAA",
            "file:///etc/a.png",
            "/abs/a.png",
            "C:\\images\\a.png",
            "missing.png",
            "notes.txt",
            "",
        ],
    )
    def test_non_local_or_unsupported_sources_are_not_followed(self, tmp_path, source):
        (tmp_path / "notes.txt").write_text("x")
        page = tmp_path / "page.html"

        assert HtmlReader.resolve_image(page, source) is None

    def test_relative_sources_resolve_including_encoded_and_parent_paths(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "my chart.PNG").write_bytes(b"x")
        (tmp_path / "top.jpg").write_bytes(b"x")
        (tmp_path / "site").mkdir()
        page = tmp_path / "site" / "page.html"

        assert HtmlReader.resolve_image(page, "../img/my%20chart.PNG?v=2#f") == (
            tmp_path / "site" / ".." / "img" / "my chart.PNG"
        )
        assert HtmlReader.resolve_image(page, "../top.jpg") is not None

    def test_local_image_text_is_appended_and_page_is_mixed(self, tmp_path):
        (tmp_path / "chart.png").write_bytes(b"x")
        page_path = tmp_path / "page.html"
        page_path.write_text('<p>Caption</p><img src="chart.png">', encoding="utf-8")

        with self._ocr(confidence=0.5):
            page = HtmlReader.read_file(MagicMock(), page_path)

        assert page.text == "Caption\nTEXT FROM IMAGE"
        assert page.source == "mixed"
        assert page.ocr_engine is not None
        assert page.confidence == pytest.approx(0.75)

    def test_same_image_is_only_ocrd_once(self, tmp_path):
        (tmp_path / "a.png").write_bytes(b"x")
        page_path = tmp_path / "page.html"
        page_path.write_text('<img src="a.png"><img src="./a.png">', encoding="utf-8")

        with self._ocr() as ocr_file:
            HtmlReader.read_file(MagicMock(), page_path)

        assert ocr_file.call_count == 1

    def test_image_count_is_capped(self, tmp_path):
        count = HtmlReader.MAX_IMAGES + 5
        for i in range(count):
            (tmp_path / f"{i}.png").write_bytes(b"x")
        page_path = tmp_path / "page.html"
        page_path.write_text(
            "".join(f'<img src="{i}.png">' for i in range(count)), encoding="utf-8"
        )

        with self._ocr() as ocr_file:
            HtmlReader.read_file(MagicMock(), page_path)

        assert ocr_file.call_count == HtmlReader.MAX_IMAGES

    def test_failing_or_empty_image_is_skipped(self, tmp_path):
        (tmp_path / "bad.png").write_bytes(b"x")
        (tmp_path / "blank.png").write_bytes(b"x")
        page_path = tmp_path / "page.html"
        page_path.write_text('<p>Body</p><img src="bad.png"><img src="blank.png">')
        results = [RuntimeError("boom"), PageResult(text="  ", confidence=0.9, source="ocr")]

        with patch("vethuq_core.ocr.ImageReader.ocr_file", side_effect=results):
            page = HtmlReader.read_file(MagicMock(), page_path)

        assert page.text == "Body"
        assert page.source == "native"
        assert page.ocr_engine is None

    def test_no_images_never_touches_the_ocr_engine(self, tmp_path):
        page_path = tmp_path / "page.html"
        page_path.write_text("<p>Body</p>")

        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            HtmlReader.read_file(MagicMock(), page_path)

        get_engine.assert_not_called()

    @patch("vethuq_core.ocr.Engine.get")
    def test_indexing_makes_image_text_searchable(self, _engine, conn, tmp_path):
        (tmp_path / "scan.png").write_bytes(b"x")
        (tmp_path / "page.html").write_text('<p>Intro</p><img src="scan.png">')
        source = Sources.add(conn, tmp_path / "page.html")

        with self._ocr(text="Invoice total 4242"):
            Quick.run(conn, source)

        assert conn.execute("SELECT status FROM document_index").fetchone()[0] == "indexed"
        assert (
            conn.execute(
                "SELECT page_count FROM confidence_metrics "
                "WHERE file_type = 'html' AND process_type = 'mixed'"
            ).fetchone()[0]
            == 1
        )
        assert [m.file_name for m in Search.indexed_content(conn, "total 4242")] == ["page.html"]


class TestXmlText:
    def test_values_are_indexed_under_their_path(self):
        lines = Markup.xml_text(XML.encode()).splitlines()

        assert "catalog/book/title: Dune" in lines
        assert "catalog/book/author: Herbert" in lines

    def test_attributes_with_namespaces_stripped(self):
        lines = Markup.xml_text(XML.encode()).splitlines()

        assert "catalog/book@id: 7" in lines
        assert "catalog/book@lang: en" in lines

    def test_mixed_content_keeps_document_order(self):
        lines = Markup.xml_text(XML.encode()).splitlines()

        assert lines.index("catalog/note: mixed") < lines.index("catalog/note/b: inline")
        assert lines.index("catalog/note/b: inline") < lines.index("catalog/note: tail")

    def test_comments_and_empty_elements_add_nothing(self):
        text = Markup.xml_text(XML.encode())

        assert "comment" not in text
        assert "empty" not in text

    def test_deeply_nested_document_does_not_overflow(self):
        depth = 5000
        data = ("<a>" * depth + "leaf" + "</a>" * depth).encode()

        assert Markup.xml_text(data).endswith(": leaf")

    def test_entity_declarations_are_refused(self):
        bomb = b'<!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>'

        with pytest.raises(ValueError):
            Markup.xml_text(bomb)


class TestReaders:
    def test_html_read_file(self, tmp_path):
        path = tmp_path / "page.html"
        path.write_text(HTML, encoding="utf-8")

        page = HtmlReader.read_file(MagicMock(), path)

        assert page.source == "native"
        assert page.confidence == 1.0
        assert page.encoding == "utf-8"
        assert page.ocr_engine is None
        assert "Total amount due is 1200." in page.text

    def test_xml_read_file(self, tmp_path):
        path = tmp_path / "data.xml"
        path.write_text(XML, encoding="utf-8")

        page = XmlReader.read_file(path)

        assert page.source == "native"
        assert page.confidence == 1.0
        assert "catalog/book/title: Dune" in page.text

    def test_malformed_xml_falls_back_to_loose_text_with_lower_confidence(self, tmp_path):
        path = tmp_path / "broken.xml"
        path.write_text("<a><b>still searchable</a>", encoding="utf-8")

        page = XmlReader.read_file(path)

        assert "still searchable" in page.text
        assert page.confidence == Markup.UNPARSED_CONFIDENCE

    def test_xml_with_entities_falls_back_without_expanding(self, tmp_path):
        path = tmp_path / "bomb.xml"
        path.write_bytes(b'<!DOCTYPE x [<!ENTITY a "boom">]><x>visible</x>')

        page = XmlReader.read_file(path)

        assert "visible" in page.text
        assert page.confidence == Markup.UNPARSED_CONFIDENCE

    @pytest.mark.parametrize(
        ("name", "file_type"),
        [
            ("a.html", "html"),
            ("a.HTM", "html"),
            ("a.xhtml", "html"),
            ("a.xml", "xml"),
        ],
    )
    def test_registered_by_suffix_case_insensitively(self, tmp_path, name, file_type):
        assert Readers.is_supported(tmp_path / name)
        assert Readers.for_path(tmp_path / name).file_type == file_type

    def test_new_file_type_counts_include_both(self):
        counts = Readers.new_file_type_counts()

        assert counts["html"] == 0
        assert counts["xml"] == 0


class TestMarkupIndexing:
    @patch("vethuq_core.ocr.Engine.get")
    def test_run_indexes_and_searches_html_and_xml_without_ocr_engine(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        (tmp_path / "page.html").write_text(HTML, encoding="utf-8")
        (tmp_path / "data.xml").write_text(XML, encoding="utf-8")
        source = Sources.add(conn, tmp_path)

        Quick.run(conn, source)

        mock_get_engine.assert_not_called()
        rows = conn.execute(
            "SELECT file_type, status FROM document_index ORDER BY file_type"
        ).fetchall()
        assert [(r["file_type"], r["status"]) for r in rows] == [
            ("html", "indexed"),
            ("xml", "indexed"),
        ]
        assert conn.execute("SELECT COUNT(*) FROM markup_pages").fetchone()[0] == 2
        for file_type in ("html", "xml"):
            confidence = conn.execute(
                "SELECT page_count FROM confidence_metrics "
                "WHERE file_type = ? AND process_type = 'native'",
                (file_type,),
            ).fetchone()
            assert confidence["page_count"] == 1

        html_matches = Search.indexed_content(conn, "AMOUNT due")
        assert [(m.file_name, m.page_number) for m in html_matches] == [("page.html", None)]
        xml_matches = Search.indexed_content(conn, "book/title: dune")
        assert [m.file_name for m in xml_matches] == ["data.xml"]

    def test_reindexing_replaces_text(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "page.html"
        path.write_text("<p>first version</p>", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        path.write_text("<p>second edition, longer</p>", encoding="utf-8")
        Quick.run(conn, source, only_new_files=True)

        assert [r["ocr_text"] for r in conn.execute("SELECT ocr_text FROM markup_pages")] == [
            "second edition, longer"
        ]

    def test_binary_file_named_html_is_marked_error(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "fake.html"
        path.write_bytes(b"\x00\x01\x02\x03" * 64)
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = conn.execute("SELECT status, error_message FROM document_index").fetchone()
        assert doc["status"] == "error"

    def test_removing_source_deletes_markup_pages(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "data.xml"
        path.write_text("<a>some searchable words</a>", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        Sources.remove(conn, source.id)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM markup_pages").fetchone()[0] == 0
