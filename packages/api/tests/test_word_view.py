"""A word-processor document made into the blocks the preview shows, over the stored text."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from vethuq_api import word_view

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

STYLES = f"""<w:styles {W}>
<w:style w:styleId="Kop1"><w:name w:val="heading 1"/></w:style>
<w:style w:styleId="Titel"><w:name w:val="Title"/></w:style>
</w:styles>"""

DOCUMENT = f"""<w:document {W}><w:body>
<w:p><w:pPr><w:pStyle w:val="Titel"/></w:pPr><w:r><w:t>Annual report</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Kop1"/></w:pPr><w:r><w:t>Summary</w:t></w:r></w:p>
<w:p><w:r><w:t>Wheat</w:t></w:r><w:r><w:t xml:space="preserve"> prices fell.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr></w:pPr>
<w:r><w:t>First point</w:t></w:r></w:p>
<w:p/>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Region</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Tonnes</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>North</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>Two</w:t><w:br/><w:t>lines</w:t></w:r></w:p>
</w:body></w:document>"""

FOOTER = f"<w:ftr {W}><w:p><w:r><w:t>Page footer</w:t></w:r></w:p></w:ftr>"

ODT = """<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
<office:body><office:text>
<text:h text:outline-level="2">Chapter</text:h>
<text:p>Plain  <text:s text:c="2"/>words</text:p>
<text:list><text:list-item><text:p>An item</text:p></text:list-item></text:list>
<table:table><table:table-row>
<table:table-cell><text:p>a</text:p></table:table-cell><table:table-cell><text:p>b</text:p></table:table-cell>
</table:table-row></table:table>
<text:p>Last</text:p>
</office:text></office:body></office:document-content>"""


def package(tmp_path, name, parts):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        for part, data in parts.items():
            z.writestr(part, data)
    return str(path)


@pytest.fixture
def docx(tmp_path):
    return package(
        tmp_path,
        "a.docx",
        {
            "word/document.xml": DOCUMENT,
            "word/styles.xml": STYLES,
            "word/footer1.xml": FOOTER,
        },
    )


@pytest.fixture
def odt(tmp_path):
    return package(tmp_path, "a.odt", {"content.xml": ODT})


class TestDocx:
    def test_structure_kinds(self, docx):
        items = word_view.structure(docx, "docx")
        assert [(i["kind"], i["first"]) for i in items] == [
            ("title", "Annual report"),
            ("heading", "Summary"),
            ("text", "Wheat prices fell."),
            ("list", "First point"),
            ("cell", "Region"),
            ("cell", "Tonnes"),
            ("cell", "North"),
            ("cell", "12"),
            ("text", "Two"),
            ("text", "Page footer"),
        ]
        assert items[1]["level"] == 1 and items[3]["level"] == 1
        assert [(i["row"], i["cell"]) for i in items[4:8]] == [(1, 1), (1, 2), (2, 1), (2, 2)]

    def test_blocks_are_the_stored_lines_with_offsets_and_kinds(self, docx):
        text = (
            "Annual report\nSummary\nWheat prices fell.\nFirst point\nRegion\nTonnes\n"
            "North\n12\nTwo\nlines\nPage footer"
        )
        blocks = word_view.layout(text, word_view.structure(docx, "docx"))
        assert [b["kind"] for b in blocks] == [
            "title",
            "heading",
            "text",
            "list",
            "cell",
            "cell",
            "cell",
            "cell",
            "text",
            "text",  # the second line of a paragraph
            "text",
        ]
        for block in blocks:
            assert text[block["start"] : block["start"] + len(block["text"])] == block["text"]

    def test_text_the_file_has_no_paragraph_for_is_plain(self, docx):
        text = "Annual report\ntext read from a picture"
        blocks = word_view.layout(text, word_view.structure(docx, "docx"))
        assert [b["kind"] for b in blocks] == ["title", "text"]

    def test_a_template_reads_as_a_document(self, docx):
        assert word_view.structure(docx, "dotx") == word_view.structure(docx, "docx")


class TestOdt:
    def test_structure_kinds(self, odt):
        items = word_view.structure(odt, "odt")
        assert [(i["kind"], i["first"]) for i in items] == [
            ("heading", "Chapter"),
            ("text", "Plain    words"),
            ("list", "An item"),
            ("row", "a\tb"),
            ("text", "Last"),
        ]
        assert items[0]["level"] == 2


class TestWhatCannotBeRead:
    def test_no_structure_is_plain_lines(self, tmp_path):
        path = tmp_path / "a.docx"
        path.write_bytes(b"not a zip")
        assert word_view.structure(str(path), "docx") == []
        assert word_view.structure(str(path), "rtf") == []
        blocks = word_view.layout("One\nTwo", [])
        assert blocks == [
            {"kind": "text", "text": "One", "start": 0},
            {"kind": "text", "text": "Two", "start": 4},
        ]

    def test_the_cache_reads_a_file_once_until_it_changes(self, docx, monkeypatch):
        calls = []
        real = word_view.structure
        monkeypatch.setattr(word_view, "structure", lambda p, k: calls.append(p) or real(p, k))
        cache = word_view.Cache()
        first = cache.get(docx, "docx")
        assert cache.get(docx, "docx") is first and len(calls) == 1
        Path(docx).write_bytes(Path(docx).read_bytes() + b"\0")
        cache.get(docx, "docx")
        assert len(calls) == 2
        assert cache.get(docx + ".gone", "docx") == []


class TestWindow:
    def blocks(self, n):
        return [{"kind": "text", "text": "x" * 9, "start": i * 10} for i in range(n)]

    def test_a_short_document_is_whole(self):
        reply = word_view.window(self.blocks(5), 23)
        assert (reply["first"], reply["total"], len(reply["blocks"])) == (0, 5, 5)

    def test_a_long_one_is_a_window_around_the_match(self, monkeypatch):
        monkeypatch.setattr(word_view, "MAX_BLOCKS", 40)
        reply = word_view.window(self.blocks(500), 2505)
        assert reply["first"] == 250 - 10 and len(reply["blocks"]) == 40
        assert reply["blocks"][10]["start"] <= 2505 <= reply["blocks"][10]["start"] + 9
        assert word_view.window(self.blocks(500), 99999)["first"] == 460


class TestTheStructureIsTheOneTheAddOnsRead:
    """The lines are found by their text, so the paragraphs must be the add-ons', one for one.
    Needs the DOCX and ODT add-ons, so these are skipped without them."""

    def test_docx(self, docx):
        parser = pytest.importorskip("vethuq_addon_docx._parsers").DocxParser
        text, _ = parser.extract(Path(docx))
        firsts = [i["first"] for i in word_view.structure(docx, "docx")]
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for first in firsts:
            assert first in lines

    def test_odt(self, odt):
        parser = pytest.importorskip("vethuq_addon_odt._parsers").OdtParser
        text, _ = parser.extract(Path(odt))
        assert [i["first"] for i in word_view.structure(odt, "odt")] == [
            line.strip() for line in text.split("\n")
        ]
