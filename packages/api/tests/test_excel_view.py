"""A spreadsheet made into the sheets and cells the preview shows, over the stored text."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from vethuq_api import excel_view

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
REL = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

WORKBOOK = f"""<workbook {NS} {REL}><sheets>
<sheet name="Prices" sheetId="1" r:id="rId1"/><sheet name="Empty" sheetId="2" r:id="rId2"/>
<sheet name="Notes" sheetId="3" r:id="rId3"/></sheets></workbook>"""
RELS = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Target="worksheets/sheet3.xml"/></Relationships>"""
SHARED = f"<sst {NS}><si><t>Region</t></si><si><t>Tonnes</t></si><si><t>North</t></si></sst>"
STYLES = (
    f"""<styleSheet {NS}><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>"""
)
SHEET1 = f"""<worksheet {NS}><sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>
<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"/><c r="C2"><v>12400</v></c></row>
<row r="4"><c r="B4" s="1"><v>45678</v></c><c r="D4" t="b"><v>1</v></c></row>
<row r="5"><c r="A5"/></row>
</sheetData></worksheet>"""
SHEET2 = f"<worksheet {NS}><sheetData><row r='1'><c r='A1'/></row></sheetData></worksheet>"
SHEET3 = f"""<worksheet {NS}><sheetData>
<row r="1"><c r="B1" t="inlineStr"><is><t>wheat</t></is></c></row></sheetData></worksheet>"""

# The text the add-ons store for the workbook above.
STORED = "Prices\nRegion\tTonnes\nNorth\t12400\n2025-01-21\tTRUE\nNotes\nwheat"

ODS = """<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
<office:body><office:spreadsheet>
<table:table table:name="Stock"><table:table-row>
<table:table-cell office:value-type="string"><text:p>Item</text:p></table:table-cell>
<table:table-cell table:number-columns-repeated="3"/>
<table:table-cell office:value-type="float" office:value="7"><text:p>7</text:p></table:table-cell>
</table:table-row>
<table:table-row table:number-rows-repeated="2">
<table:covered-table-cell/><table:table-cell office:value-type="string"><text:p>x</text:p>
</table:table-cell></table:table-row></table:table>
</office:spreadsheet></office:body></office:document-content>"""
ODS_STORED = "Stock\nItem\t7\nx\nx"


def package(tmp_path, name, parts):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        for part, data in parts.items():
            z.writestr(part, data)
    return str(path)


@pytest.fixture
def xlsx(tmp_path):
    return package(
        tmp_path,
        "a.xlsx",
        {
            "xl/workbook.xml": WORKBOOK,
            "xl/_rels/workbook.xml.rels": RELS,
            "xl/sharedStrings.xml": SHARED,
            "xl/styles.xml": STYLES,
            "xl/worksheets/sheet1.xml": SHEET1,
            "xl/worksheets/sheet2.xml": SHEET2,
            "xl/worksheets/sheet3.xml": SHEET3,
        },
    )


@pytest.fixture
def ods(tmp_path):
    return package(tmp_path, "a.ods", {"content.xml": ODS})


class TestXlsx:
    def test_cells_with_their_places(self, xlsx):
        sheets = excel_view.sheets_of(xlsx, "xlsx")
        assert [s["name"] for s in sheets] == ["Prices", "Empty", "Notes"]
        assert sheets[0]["rows"] == [
            (1, [(0, "Region", False), (2, "Tonnes", False)]),
            (2, [(0, "North", False), (2, "12400", True)]),
            (4, [(1, "2025-01-21", False), (3, "TRUE", False)]),
        ]
        assert sheets[1]["rows"] == []

    def test_laid_over_the_stored_text(self, xlsx):
        laid = excel_view.layout(STORED, excel_view.sheets_of(xlsx, "xlsx"))
        prices, empty, notes = laid["sheets"]
        assert prices["name_start"] == 0 and empty["name_start"] is None
        assert prices["numbers"] == [1, 2, 4]
        for row in prices["rows"] + notes["rows"]:
            for _, text, _, start in row:
                assert STORED[start : start + len(text)] == text
        assert prices["rows"][1][1] == [2, "12400", True, STORED.index("12400")]
        assert notes["numbers"] == [1] and notes["rows"][0][0][0] == 1
        assert laid["notes"] == []

    def test_a_line_the_file_has_no_row_for_is_a_note(self, xlsx):
        text = STORED + "\nA comment on a cell"
        laid = excel_view.layout(text, excel_view.sheets_of(xlsx, "xlsx"))
        assert laid["notes"] == [{"text": "A comment on a cell", "start": len(STORED) + 1}]

    def test_the_window_is_the_sheet_with_the_match(self, xlsx):
        laid = excel_view.layout(STORED, excel_view.sheets_of(xlsx, "xlsx"))
        first = excel_view.window(laid, None, None, None)
        assert first["sheet"] == 0 and [s["rows"] for s in first["sheets"]] == [3, 0, 1]
        assert [s["cols"] for s in first["sheets"]] == [4, 0, 2]
        assert [r["r"] for r in first["rows"]] == [1, 2, 4]
        at = STORED.index("wheat")
        found = excel_view.window(laid, at, None, None)
        assert found["sheet"] == 2 and found["rows"][0]["cells"][0]["t"] == "wheat"
        assert excel_view.window(laid, at, 0, None)["sheet"] == 0
        assert excel_view.window(laid, 0, 99, None)["sheet"] == 0

    def test_a_long_sheet_is_a_window_around_the_match(self, monkeypatch):
        monkeypatch.setattr(excel_view, "MAX_ROWS", 40)
        rows = [(n, [(0, f"v{n:04}", False)]) for n in range(1, 501)]
        text = "S\n" + "\n".join(f"v{n:04}" for n in range(1, 501))
        laid = excel_view.layout(text, [{"name": "S", "rows": rows}])
        reply = excel_view.window(laid, text.index("v0250"), None, None)
        assert (reply["first"], len(reply["rows"])) == (249 - 10, 40)
        assert excel_view.window(laid, None, 0, 460)["first"] == 460
        assert excel_view.window(laid, None, 0, 9999)["first"] == 499

    def test_without_cells_the_stored_rows_are_one_sheet(self):
        laid = excel_view.layout("a\tb\n\nc", [])
        (sheet,) = laid["sheets"]
        assert sheet["numbers"] == [1, 2]
        assert [(c[0], c[1], c[3]) for c in sheet["rows"][0]] == [(0, "a", 0), (1, "b", 2)]
        assert sheet["rows"][1][0][3] == 5

    def test_not_a_workbook_is_the_stored_rows(self, tmp_path):
        path = tmp_path / "b.xlsx"
        path.write_bytes(b"not a zip")
        assert excel_view.sheets_of(str(path), "xlsx") == []
        assert excel_view.sheets_of(str(path), "csv") == []

    def test_the_cache_reads_a_file_once_until_it_changes(self, xlsx, monkeypatch):
        calls = []
        real = excel_view.sheets_of
        monkeypatch.setattr(excel_view, "sheets_of", lambda p, k: calls.append(p) or real(p, k))
        cache = excel_view.Cache()
        first = cache.get(xlsx, "xlsx", STORED)
        assert cache.get(xlsx, "xlsx", STORED) is first and len(calls) == 1
        Path(xlsx).write_bytes(Path(xlsx).read_bytes() + b"\0")
        cache.get(xlsx, "xlsx", STORED)
        assert len(calls) == 2
        assert cache.get(xlsx + ".gone", "xlsx", "a\tb")["sheets"][0]["rows"]


class TestOds:
    def test_cells_with_their_places(self, ods):
        (sheet,) = excel_view.sheets_of(ods, "ods")
        assert sheet["name"] == "Stock"
        assert sheet["rows"][0] == (1, [(0, "Item", False), (4, "7", True)])
        # A repeated row is its copies, and a merged (covered) cell still takes its column.
        assert [(n, cells) for n, cells in sheet["rows"][1:]] == [
            (2, [(1, "x", False)]),
            (3, [(1, "x", False)]),
        ]

    def test_laid_over_the_stored_text(self, ods):
        laid = excel_view.layout(ODS_STORED, excel_view.sheets_of(ods, "ods"))
        (sheet,) = laid["sheets"]
        assert sheet["numbers"] == [1, 2, 3] and laid["notes"] == []
        assert sheet["rows"][0][1][3] == ODS_STORED.index("7")


class TestTheCellsAreTheOnesTheAddOnsRead:
    """The lines are found by their text, so the rows must be the add-ons', one for one. Needs the
    add-ons, so these are skipped without them."""

    @staticmethod
    def lines(sheets):
        out = []
        for sheet in sheets:
            if sheet["rows"]:
                out.append(sheet["name"])
                out.extend("\t".join(c[1] for c in cells) for _, cells in sheet["rows"])
        return out

    def test_xlsx(self, xlsx):
        parser = pytest.importorskip("vethuq_addon_xlsx._parsers").XlsxParser
        text, _ = parser.extract(Path(xlsx))
        assert text == STORED
        assert self.lines(excel_view.sheets_of(xlsx, "xlsx")) == text.split("\n")

    def test_ods(self, ods):
        parser = pytest.importorskip("vethuq_addon_ods._parsers").OdsParser
        text, _ = parser.extract(Path(ods))
        assert text == ODS_STORED
        assert self.lines(excel_view.sheets_of(ods, "ods")) == text.split("\n")
