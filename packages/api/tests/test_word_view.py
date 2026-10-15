"""A word-processor document made into the blocks the preview shows, over the stored text."""

from __future__ import annotations

import re
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
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
<office:automatic-styles>
<style:style style:name="T1" style:family="text">
<style:text-properties fo:font-weight="bold"/></style:style>
<style:style style:name="T2" style:family="text">
<style:text-properties fo:font-style="italic" style:text-underline-style="solid"
 fo:color="#ff0000" fo:font-size="150%" style:text-position="super 58%"/></style:style>
<style:style style:name="T3" style:family="text" style:parent-style-name="T1">
<style:text-properties style:text-line-through-style="solid"/></style:style>
<style:style style:name="P1" style:family="paragraph">
<style:paragraph-properties fo:text-align="center"/></style:style>
<style:style style:name="P2" style:family="paragraph">
<style:text-properties fo:font-weight="bold"/></style:style>
</office:automatic-styles>
<office:body><office:text>
<text:h text:outline-level="2">Chapter <text:span text:style-name="T1">one</text:span></text:h>
<text:p>Plain  <text:s text:c="2"/>words <text:span text:style-name="T1">bold</text:span> <text:span
 text:style-name="T2">x</text:span></text:p>
<text:p text:style-name="P1">Centred <text:a><text:span text:style-name="T3">gone</text:span>
</text:a></text:p>
<text:p text:style-name="P2">Whole paragraph bold</text:p>
<text:list><text:list-item><text:p>An item</text:p>
<text:list><text:list-item><text:p>Nested</text:p></text:list-item></text:list>
</text:list-item></text:list>
<table:table><table:table-row>
<table:table-cell><text:p>a</text:p></table:table-cell>
<table:table-cell><text:p><text:span text:style-name="T1">b</text:span></text:p></table:table-cell>
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
            ("heading", "Chapter one"),
            ("text", "Plain    words bold x"),
            ("text", "Centred gone"),
            ("text", "Whole paragraph bold"),
            ("list", "An item"),
            ("list", "Nested"),
            ("row", "a\tb"),
            ("text", "Last"),
        ]
        assert items[0]["level"] == 2
        assert [i["level"] for i in items[4:6]] == [0, 1]

    def test_formatting(self, odt):
        items = {i["first"]: i for i in word_view.structure(odt, "odt")}
        # A heading is set larger by the preview, so only the words' own look is kept.
        assert items["Chapter one"]["spans"] == [{"start": 8, "end": 11, "b": True}]
        plain = items["Plain    words bold x"]
        assert plain["spans"][0] == {"start": 15, "end": 19, "b": True}
        assert plain["spans"][1] == {
            "start": 20,
            "end": 21,
            "i": True,
            "u": True,
            "color": "#ff0000",
            "size": 1.5,
            "pos": "super",
        }
        centred = items["Centred gone"]
        assert centred["align"] == "center"
        assert centred["spans"] == [{"start": 8, "end": 12, "b": True, "s": True}]
        # A paragraph's own style sets the whole paragraph.
        assert items["Whole paragraph bold"]["spans"] == [{"start": 0, "end": 20, "b": True}]
        assert items["a\tb"]["spans"] == [{"start": 2, "end": 3, "b": True}]
        assert "spans" not in items["Last"]

    def test_the_stored_line_gets_the_formatting(self, odt):
        text = "Chapter one\nPlain    words bold\n"
        blocks = word_view.layout(text, word_view.structure(odt, "odt"))
        assert blocks[0]["spans"] == [{"start": 8, "end": 11, "b": True}]
        assert blocks[1]["text"].startswith("Plain")

    def test_a_template_reads_as_a_document(self, odt):
        assert word_view.structure(odt, "ott") == word_view.structure(odt, "odt")


RTF = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\fcharset0 Arial;}}"
    b"{\\colortbl;\\red255\\green0\\blue0;}{\\stylesheet{\\s1\\b\\fs36 heading 1;}}\n"
    b"\\pard\\s1 Annual Report\\par\n"
    b"\\pard\\qc\\b\\fs32 Centered bold\\b0\\fs24\\par\n"
    b"\\pard Wheat \\i fell\\i0  and \\ul prices\\ulnone  were \\cf1 red\\cf0  caf\\'e9 done\\par\n"
    b"\\pard\\intbl a\\cell b\\cell\\row\n"
    b"\\pard Last   line\\par\n}"
)


class TestRtf:
    @pytest.fixture
    def rtf(self, tmp_path):
        pytest.importorskip("striprtf")
        path = tmp_path / "a.rtf"
        path.write_bytes(RTF)
        return str(path)

    @staticmethod
    def stored(rtf):
        """The text the RTF add-on stores for the file."""
        from striprtf.striprtf import rtf_to_text

        text = rtf_to_text(Path(rtf).read_bytes().decode("latin-1"), errors="ignore")
        lines = (re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines())
        return "\n".join(line for line in lines if line)

    def test_the_paragraphs_are_the_stored_lines(self, rtf):
        items = word_view.structure(rtf, "rtf")
        assert [i["first"] for i in items] == self.stored(rtf).split("\n")

    def test_kinds_and_formatting(self, rtf):
        blocks = word_view.layout(self.stored(rtf), word_view.structure(rtf, "rtf"))
        assert [b["kind"] for b in blocks] == ["heading", "text", "text", "row", "text"]
        assert blocks[0]["level"] == 1
        assert blocks[1]["align"] == "center"
        assert blocks[1]["spans"] == [{"start": 0, "end": 13, "b": True, "size": 1.33}]
        spans = {(s["start"], s["end"]): s for s in blocks[2]["spans"]}
        assert spans[(6, 10)] == {"start": 6, "end": 10, "i": True}
        assert spans[(15, 21)]["u"] is True
        assert [s["color"] for s in blocks[2]["spans"] if "color" in s] == ["#ff0000"]
        assert blocks[2]["text"] == "Wheat fell and prices were red café done"
        assert (blocks[3]["text"], blocks[3]["sep"]) == ("a|b|", "|")
        assert blocks[4]["text"] == "Last line" and "spans" not in blocks[4]

    def test_the_formatting_is_dropped_when_the_line_is_not_the_files(self, rtf):
        blocks = word_view.layout("Centered bold ", word_view.structure(rtf, "rtf"))
        assert "spans" not in blocks[0]

    def test_not_an_rtf_or_too_large_is_plain(self, tmp_path, monkeypatch):
        pytest.importorskip("striprtf")
        path = tmp_path / "b.rtf"
        path.write_bytes(b"plain text")
        assert word_view.structure(str(path), "rtf") == []
        path.write_bytes(RTF)
        monkeypatch.setattr(word_view, "MAX_RTF_BYTES", 10)
        assert word_view.structure(str(path), "rtf") == []

    def test_the_text_is_the_addons(self, rtf):
        parser = pytest.importorskip("vethuq_addon_rtf._parsers").RtfParser
        text, _ = parser.extract(Path(rtf))
        assert text == self.stored(rtf)
        assert [i["first"] for i in word_view.structure(rtf, "rtf")] == text.split("\n")


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
