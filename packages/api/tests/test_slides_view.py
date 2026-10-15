"""A presentation made into the slides the preview shows, over the stored text."""

from __future__ import annotations

import importlib.util
import struct
import sys
import zipfile
from pathlib import Path

import pytest

from vethuq_api import slides_view

MSG_TESTS = (
    Path(__file__).resolve().parents[3].parent
    / "VethuQ-premium/packages/add-ons/file-types/msg/tests"
)

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

PRESENTATION = f"""<p:presentation {P} {R}><p:sldIdLst>
<p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>"""
PRESENTATION_RELS = """<Relationships
 xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="x/slide" Target="slides/slide1.xml"/>
<Relationship Id="rId2" Type="x/slide" Target="slides/slide2.xml"/></Relationships>"""


def shape(text, ph=None, level=None):
    holder = f'<p:nvPr><p:ph type="{ph}"/></p:nvPr>' if ph else ""
    props = f'<a:pPr lvl="{level}"/>' if level is not None else ""
    return (
        f"<p:sp><p:nvSpPr><p:cNvPr id='1' name='s'/><p:cNvSpPr/>{holder}</p:nvSpPr>"
        f"<p:txBody><a:p>{props}<a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>"
    )


# Slide 2 in the file is the first in the deck (the order comes from `sldIdLst`).
SLIDE2 = f"""<p:sld {P} {A}><p:cSld><p:spTree>
{shape("Harvest review", "title")}
{shape("Wheat prices fell", "body", 0)}
{shape("North up", "body", 1)}
{shape("A text box")}
<p:graphicFrame><a:graphic><a:graphicData><a:tbl>
<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Region</a:t></a:r></a:p></a:txBody></a:tc>
<a:tc><a:txBody><a:p><a:r><a:t>Tonnes</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
</a:tbl></a:graphicData></a:graphic></p:graphicFrame>
</p:spTree></p:cSld></p:sld>"""
SLIDE1 = f"""<p:sld {P} {A}><p:cSld><p:spTree>
{shape("Outlook", "ctrTitle")}{shape("Subtitle here", "subTitle")}
</p:spTree></p:cSld></p:sld>"""
SLIDE2_RELS = """<Relationships
 xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="x/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
</Relationships>"""
NOTES = f"""<p:notes {P} {A}><p:cSld><p:spTree>
{shape("Say this aloud", "body")}{shape("1", "sldNum")}
</p:spTree></p:cSld></p:notes>"""
COMMENT = f"<p:cmLst {P}><p:cm><p:text>Check the figures</p:text></p:cm></p:cmLst>"

STORED = (
    "Harvest review\nWheat prices fell\nNorth up\nA text box\nRegion\tTonnes\n"
    "Outlook\nSubtitle here\nSay this aloud\nCheck the figures"
)

ODP = """<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
<office:body><office:presentation>
<draw:page draw:name="one">
<draw:frame presentation:class="title"><draw:text-box><text:p>Welcome</text:p>
</draw:text-box></draw:frame>
<draw:frame presentation:class="outline"><draw:text-box>
<text:list><text:list-item><text:p>First point</text:p>
<text:list><text:list-item><text:p>Nested</text:p></text:list-item></text:list>
</text:list-item></text:list></draw:text-box></draw:frame>
<presentation:notes><draw:frame presentation:class="notes"><draw:text-box>
<text:p>Speak slowly</text:p></draw:text-box></draw:frame></presentation:notes>
</draw:page>
<draw:page draw:name="two"><draw:frame><draw:text-box><text:p>Plain text</text:p>
</draw:text-box></draw:frame></draw:page>
</office:presentation></office:body></office:document-content>"""
ODP_STORED = "Welcome\nFirst point\nNested\nSpeak slowly\n\nPlain text"


def package(tmp_path, name, parts):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        for part, data in parts.items():
            z.writestr(part, data)
    return str(path)


@pytest.fixture
def pptx(tmp_path):
    return package(
        tmp_path,
        "a.pptx",
        {
            "ppt/presentation.xml": PRESENTATION,
            "ppt/_rels/presentation.xml.rels": PRESENTATION_RELS,
            "ppt/slides/slide1.xml": SLIDE1,
            "ppt/slides/slide2.xml": SLIDE2,
            "ppt/slides/_rels/slide2.xml.rels": SLIDE2_RELS,
            "ppt/notesSlides/notesSlide1.xml": NOTES,
            "ppt/comments/comment1.xml": COMMENT,
        },
    )


@pytest.fixture
def odp(tmp_path):
    return package(tmp_path, "a.odp", {"content.xml": ODP})


def summary(laid):
    return [
        [(i["kind"], i["level"], [line["text"] for line in i["lines"]]) for i in s["items"]]
        for s in laid["slides"]
    ]


class TestPptx:
    def test_the_paragraphs_in_the_stored_order_with_their_kinds(self, pptx):
        entries, count = slides_view.entries_of(pptx, "pptx")
        assert count == 2
        assert [(e["slide"], e["kind"], e["level"], e["text"]) for e in entries] == [
            (0, "title", 0, "Harvest review"),
            (0, "list", 0, "Wheat prices fell"),
            (0, "list", 1, "North up"),
            (0, "text", 0, "A text box"),
            (0, "row", 0, "Region\tTonnes"),
            (1, "title", 0, "Outlook"),
            (1, "subtitle", 0, "Subtitle here"),
            (0, "note", 0, "Say this aloud"),
            (None, "comment", 0, "Check the figures"),
        ]

    def test_laid_over_the_stored_text(self, pptx):
        entries, count = slides_view.entries_of(pptx, "pptx")
        laid = slides_view.layout(STORED, entries, count)
        assert [[i[0] for i in s] for s in summary(laid)] == [
            ["title", "list", "list", "text", "row", "note"],
            ["title", "subtitle"],
        ]
        for slide in laid["slides"]:
            for item in slide["items"]:
                for line in item["lines"]:
                    assert STORED[line["start"] : line["start"] + len(line["text"])] == line["text"]
        assert laid["notes"] == [{"text": "Check the figures", "start": STORED.index("Check")}]

    def test_a_line_the_file_has_no_paragraph_for_is_a_note(self, pptx):
        entries, count = slides_view.entries_of(pptx, "pptx")
        laid = slides_view.layout(STORED + "\nSmartArt words", entries, count)
        assert [n["text"] for n in laid["notes"]] == ["Check the figures", "SmartArt words"]

    def test_a_paragraph_of_several_lines_is_one_item(self):
        entries = [{"slide": 0, "kind": "text", "level": 0, "text": "one\ntwo"}]
        laid = slides_view.layout("one\ntwo", entries, 1)
        assert summary(laid) == [[("text", 0, ["one", "two"])]]

    def test_the_window_has_an_outline_and_the_slides_around_the_match(self, pptx, monkeypatch):
        entries, count = slides_view.entries_of(pptx, "pptx")
        laid = slides_view.layout(STORED, entries, count)
        reply = slides_view.window(laid, None, None)
        assert reply["outline"] == [
            {"n": 1, "title": "Harvest review"},
            {"n": 2, "title": "Outlook"},
        ]
        assert (reply["first"], reply["total"], [s["n"] for s in reply["slides"]]) == (0, 2, [1, 2])
        monkeypatch.setattr(slides_view, "MAX_SLIDES", 4)
        entries = [
            {"slide": n, "kind": "title", "level": 0, "text": f"Slide {n:03}"} for n in range(100)
        ]
        text = "\n".join(e["text"] for e in entries)
        laid = slides_view.layout(text, entries, 100)
        reply = slides_view.window(laid, text.index("Slide 050"), None)
        assert (reply["first"], [s["n"] for s in reply["slides"]]) == (49, [50, 51, 52, 53])
        assert slides_view.window(laid, None, 90)["first"] == 90
        assert slides_view.window(laid, None, 9999)["first"] == 99


class TestOdp:
    def test_kinds_and_levels(self, odp):
        entries, count = slides_view.entries_of(odp, "odp")
        assert count == 2
        assert [(e["slide"], e["kind"], e["level"], e["text"]) for e in entries] == [
            (0, "title", 0, "Welcome"),
            (0, "list", 0, "First point"),
            (0, "list", 1, "Nested"),
            (0, "note", 0, "Speak slowly"),
            (1, "text", 0, "Plain text"),
        ]
        laid = slides_view.layout(ODP_STORED, entries, count)
        assert [len(s["items"]) for s in laid["slides"]] == [4, 1]


class TestWhatCannotBeRead:
    def test_no_slides_is_the_stored_lines_in_one_slide(self, tmp_path):
        path = tmp_path / "b.pptx"
        path.write_bytes(b"not a zip")
        assert slides_view.entries_of(str(path), "pptx") == ([], 0)
        assert slides_view.entries_of(str(path), "docx") == ([], 0)
        laid = slides_view.layout("One\n\nTwo", [], 0)
        assert summary(laid) == [[("text", 0, ["One"]), ("text", 0, ["Two"])]]
        assert laid["notes"] == []

    def test_the_cache_reads_a_file_once_until_it_changes(self, pptx, monkeypatch):
        calls = []
        real = slides_view.entries_of
        monkeypatch.setattr(slides_view, "entries_of", lambda p, k: calls.append(p) or real(p, k))
        cache = slides_view.Cache()
        first = cache.get(pptx, "pptx", STORED)
        assert cache.get(pptx, "pptx", STORED) is first and len(calls) == 1
        Path(pptx).write_bytes(Path(pptx).read_bytes() + b"\0")
        cache.get(pptx, "pptx", STORED)
        assert len(calls) == 2
        assert cache.get(pptx + ".gone", "pptx", "a\nb")["slides"][0]["items"]


def record(version, rec_type, data=b"", instance=0):
    return struct.pack("<HHI", version | instance << 4, rec_type, len(data)) + data


def ppt_file(tmp_path):
    path = MSG_TESTS / "msg_fixtures.py"
    if not path.exists():
        pytest.skip("the MSG add-on's test fixtures are not next to this checkout")
    pytest.importorskip("olefile")
    spec = importlib.util.spec_from_file_location("msg_fixtures_for_slides", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    def text(kind, value):
        return record(0, 0x0F9F, struct.pack("<I", kind)) + record(
            0, 0x0FA0, value.encode("utf-16-le")
        )

    slide = record(0xF, 0x03EE, text(0, "Quarterly review") + text(1, "Wheat fell\rPrices up"))
    second = record(0xF, 0x03EE, text(4, "Closing"))
    notes = record(0xF, 0x03F0, text(2, "Say hello"))
    stream = record(0xF, 0x03E8, slide + second + notes)
    # Streams under 4096 bytes would be in the mini stream: pad them (see the MSG fixtures).
    data = stream.ljust(4096, b"\0")
    root = module.Node("Root Entry", children=[module.stream("PowerPoint Document", data)])
    target = tmp_path / "a.ppt"
    target.write_bytes(module.build(root))
    return str(target)


class TestPpt:
    def test_slides_kinds_and_notes(self, tmp_path):
        path = ppt_file(tmp_path)
        entries, count = slides_view.entries_of(path, "ppt")
        assert count == 2
        assert [(e["slide"], e["kind"], e["text"]) for e in entries] == [
            (0, "title", "Quarterly review"),
            (0, "list", "Wheat fell\nPrices up"),
            (1, "text", "Closing"),
            (None, "note", "Say hello"),
        ]


class TestTheParagraphsAreTheOnesTheAddOnsRead:
    """The lines are found by their text, so the paragraphs must be the add-ons', one for one.
    Needs the add-ons, so these are skipped without them."""

    @staticmethod
    def lines(entries):
        return [line for e in entries for line in e["text"].split("\n") if line.strip()]

    def test_pptx(self, pptx):
        parser = pytest.importorskip("vethuq_addon_pptx._parsers").PptxParser
        text, _ = parser.extract(Path(pptx))
        assert text == STORED
        entries, _ = slides_view.entries_of(pptx, "pptx")
        assert self.lines(entries) == text.split("\n")

    def test_odp(self, odp):
        parser = pytest.importorskip("vethuq_addon_odp._parsers").OdpParser
        text, _ = parser.extract(Path(odp))
        assert text == ODP_STORED
        entries, _ = slides_view.entries_of(odp, "odp")
        assert self.lines(entries) == [line for line in text.split("\n") if line]

    def test_ppt(self, tmp_path):
        parser = pytest.importorskip("vethuq_addon_ppt._parsers").PptParser
        path = ppt_file(tmp_path)
        text, _ = parser.extract(Path(path))
        entries, _ = slides_view.entries_of(path, "ppt")
        assert self.lines(entries) == text.split("\n")
