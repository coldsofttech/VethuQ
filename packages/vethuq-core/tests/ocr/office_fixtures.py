"""Builders for tiny Word files, so tests don't need binary fixtures."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import cv2
import numpy as np

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def png_bytes(width: int = 120, height: int = 80) -> bytes:
    ok, encoded = cv2.imencode(".png", np.full((height, width, 3), 200, dtype=np.uint8))
    assert ok
    return encoded.tobytes()


def jpg_bytes(width: int = 120, height: int = 80) -> bytes:
    ok, encoded = cv2.imencode(".jpg", np.full((height, width, 3), 200, dtype=np.uint8))
    assert ok
    return encoded.tobytes()


def docx_document_xml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        f"<w:body>{body}</w:body></w:document>"
    )


def paragraph(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def write_docx(
    path: Path,
    body: str,
    *,
    media: dict[str, bytes] | None = None,
    parts: dict[str, str] | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", docx_document_xml(body))
        for name, data in (media or {}).items():
            package.writestr(f"word/media/{name}", data)
        for name, xml in (parts or {}).items():
            package.writestr(name, xml)
    return path


def build_doc_streams(*, table_stream_1: bool = True, encrypted: bool = False):
    """A `WordDocument` stream and `{name: bytes}` table streams holding two text pieces:
    an 8-bit one ("Hello\\r") and a UTF-16 one ("Wörld€\\r")."""
    word = bytearray(0x400)
    flags = (0x0200 if table_stream_1 else 0) | (0x0100 if encrypted else 0)
    struct.pack_into("<HHH", word, 0, 0xA5EC, 0x00C1, 0)
    struct.pack_into("<H", word, 0x0A, flags)

    first = "Hello\r".encode("cp1252")
    second = "Wörld€\r".encode("utf-16-le")
    word[0x200 : 0x200 + len(first)] = first
    word[0x300 : 0x300 + len(second)] = second

    cps = struct.pack("<3I", 0, 6, 13)
    pcd1 = struct.pack("<HIH", 0, (0x200 * 2) | 0x40000000, 0)
    pcd2 = struct.pack("<HIH", 0, 0x300, 0)
    plc = cps + pcd1 + pcd2
    clx = b"\x01" + struct.pack("<H", 2) + b"\x00\x00" + b"\x02" + struct.pack("<I", len(plc)) + plc
    padding = b"\xaa" * 10
    struct.pack_into("<II", word, 0x01A2, len(padding), len(clx))
    table = padding + clx
    return bytes(word), {("1Table" if table_stream_1 else "0Table"): table}


def blip_record(data: bytes, *, png: bool, two_uids: bool = False) -> bytes:
    instance = (0x6E1 if two_uids else 0x6E0) if png else (0x46B if two_uids else 0x46A)
    uids = b"\x11" * (32 if two_uids else 16)
    payload = uids + b"\xff" + data
    return struct.pack("<HHI", instance << 4, 0xF01E if png else 0xF01D, len(payload)) + payload


# --- Excel ---------------------------------------------------------------------------

S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# cellXfs: 0 = General, 1 = built-in date (14), 2 = custom "yyyy-mm-dd hh:mm", 3 = a custom
# format with only quoted literals ("days"), which is not a date.
XLSX_STYLES = (
    f'<styleSheet xmlns="{S_NS}"><numFmts count="2">'
    '<numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd\\ hh:mm"/>'
    '<numFmt numFmtId="165" formatCode="0&quot; days&quot;"/></numFmts>'
    '<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/>'
    '<xf numFmtId="165"/></cellXfs></styleSheet>'
)


def cell(ref: str, value: str | float | None = None, *, kind: str | None = None, style: int = 0):
    t = f' t="{kind}"' if kind else ""
    s = f' s="{style}"' if style else ""
    return f'<c r="{ref}"{t}{s}><v>{value}</v></c>'


def inline_cell(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def sheet_xml(rows: list[list[str]], *, ns: str = S_NS) -> str:
    body = "".join(f'<row r="{i}">{"".join(cells)}</row>' for i, cells in enumerate(rows, start=1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>'
    )


def shared_strings_xml(*items: str) -> str:
    return (
        f'<sst xmlns="{S_NS}" count="{len(items)}" uniqueCount="{len(items)}">'
        + "".join(item if item.startswith("<si") else f"<si><t>{item}</t></si>" for item in items)
        + "</sst>"
    )


def write_xlsx(
    path: Path,
    sheets: dict[str, str],
    *,
    shared: tuple[str, ...] = (),
    styles: str | None = XLSX_STYLES,
    date1904: bool = False,
    media: dict[str, bytes] | None = None,
    parts: dict[str, str] | None = None,
    rels: bool = True,
) -> Path:
    """`sheets` maps sheet name -> worksheet XML (see `sheet_xml`), in workbook order."""
    entries = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheets, start=1)
    )
    workbook = (
        f'<workbook xmlns="{S_NS}" xmlns:r="{R_NS}">'
        f'<workbookPr date1904="{int(date1904)}"/><sheets>{entries}</sheets></workbook>'
    )
    relationships = "".join(
        f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("xl/workbook.xml", workbook)
        if rels:
            package.writestr(
                "xl/_rels/workbook.xml.rels",
                f'<Relationships xmlns="{PKG_REL_NS}">{relationships}</Relationships>',
            )
        for i, xml in enumerate(sheets.values(), start=1):
            package.writestr(f"xl/worksheets/sheet{i}.xml", xml)
        if shared:
            package.writestr("xl/sharedStrings.xml", shared_strings_xml(*shared))
        if styles:
            package.writestr("xl/styles.xml", styles)
        for name, data in (media or {}).items():
            package.writestr(f"xl/media/{name}", data)
        for name, xml in (parts or {}).items():
            package.writestr(name, xml)
    return path


def _biff(record_type: int, body: bytes = b"") -> bytes:
    return struct.pack("<HH", record_type, len(body)) + body


def _bof(kind: int) -> bytes:
    return _biff(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 0x07CC, 0, 6))


def _xf(format_id: int) -> bytes:
    return _biff(0x00E0, struct.pack("<HHHBBBBIIH", 0, format_id, 0, 0, 0, 0, 0, 0, 0, 0))


def _biff_string(text: str) -> bytes:
    return struct.pack("<HB", len(text), 1) + text.encode("utf-16-le")


def build_xls_stream(
    sheets: dict[str, list[list[object]]],
    *,
    date1904: bool = False,
    drawing_group: bytes | None = None,
) -> bytes:
    """A raw BIFF8 workbook stream (what lives in an .xls file's `Workbook` stream).

    Cells are `str` (shared string), `int`/`float` (number), `bool`, `("date", serial)`
    or `None` (skipped). A sheet is a list of rows. `drawing_group`, if given, becomes
    an MSODRAWINGGROUP record split into CONTINUE records every 8224 bytes, as Excel does.
    """
    strings: list[str] = []
    for rows in sheets.values():
        for row in rows:
            strings.extend(v for v in row if isinstance(v, str) and v not in strings)

    sst_body = struct.pack("<II", len(strings), len(strings)) + b"".join(
        _biff_string(text) for text in strings
    )
    group = b""
    if drawing_group is not None:
        pieces = [drawing_group[i : i + 8224] for i in range(0, len(drawing_group), 8224)] or [b""]
        group = _biff(0x00EB, pieces[0]) + b"".join(_biff(0x003C, piece) for piece in pieces[1:])

    def globals_part(offsets: list[int]) -> bytes:
        bounds = b"".join(
            _biff(
                0x0085,
                struct.pack("<IBB", offset, 0, 0)
                + struct.pack("<BB", len(name), 1)
                + name.encode("utf-16-le"),
            )
            for name, offset in zip(sheets, offsets, strict=True)
        )
        return (
            _bof(0x0005)
            + _biff(0x0042, struct.pack("<H", 1252))
            + _biff(0x0022, struct.pack("<H", int(date1904)))
            + _xf(0)
            + _xf(14)
            + bounds
            + group
            + _biff(0x00FC, sst_body)
            + _biff(0x000A)
        )

    def sheet_part(rows: list[list[object]]) -> bytes:
        out = _bof(0x0010) + _biff(0x0200, struct.pack("<IIHHH", 0, len(rows), 0, 8, 0))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if value is None:
                    continue
                if isinstance(value, bool):
                    out += _biff(0x0205, struct.pack("<HHHBB", r, c, 0, int(value), 0))
                elif isinstance(value, str):
                    out += _biff(0x00FD, struct.pack("<HHHI", r, c, 0, strings.index(value)))
                elif isinstance(value, tuple):
                    out += _biff(0x0203, struct.pack("<HHHd", r, c, 1, float(value[1])))
                else:
                    out += _biff(0x0203, struct.pack("<HHHd", r, c, 0, float(value)))
        return out + _biff(0x000A)

    parts = [sheet_part(rows) for rows in sheets.values()]
    head = globals_part([0] * len(sheets))
    offsets, position = [], len(head)
    for part in parts:
        offsets.append(position)
        position += len(part)
    return globals_part(offsets) + b"".join(parts)


def write_xls(path: Path, sheets: dict[str, list[list[object]]], **kwargs) -> Path:
    """Write a BIFF8 workbook that `xlrd` reads, without an OLE container around it."""
    path.write_bytes(build_xls_stream(sheets, **kwargs))
    return path
