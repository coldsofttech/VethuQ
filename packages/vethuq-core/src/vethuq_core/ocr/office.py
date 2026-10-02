"""Pulling text and embedded images out of Word, Excel and PowerPoint files, with no OCR and
no database.

`DocxParser`, `XlsxParser` and `PptxParser` read the Office Open XML package directly (it's a
zip of XML parts), so they need nothing beyond the standard library. `DocParser` reads the
legacy Word binary format (an OLE compound file) through `olefile`; `XlsParser` reads the
legacy Excel format through `xlrd`, and carves pictures out with `olefile` the way
`DocParser` does; `PptParser` reads the legacy PowerPoint format's record stream through
`olefile` and carves its pictures the same way.
"""

from __future__ import annotations

import io
import logging
import posixpath
import re
import struct
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

_logger = logging.getLogger(__name__)


class DocxParser:
    _W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    _MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

    # A part is parsed into memory whole; a corrupt or hostile file could claim far more.
    MAX_XML_PART_BYTES = 128 * 1024 * 1024
    MAX_IMAGE_BYTES = 64 * 1024 * 1024

    IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")

    # Main body first, then everything else that carries text, in a stable order.
    _EXTRA_PART = re.compile(r"^word/(header|footer)\d*\.xml$|^word/(footnotes|endnotes)\.xml$")

    @staticmethod
    def extract(file_path: Path) -> tuple[str, list[bytes]]:
        """Return `(text, images)`: the document's text, and its raster images' raw bytes."""
        try:
            with zipfile.ZipFile(file_path) as package:
                names = package.namelist()
                if "word/document.xml" not in names:
                    raise ValueError("not a Word document: word/document.xml is missing")
                parts = ["word/document.xml"] + sorted(
                    name for name in names if DocxParser._EXTRA_PART.match(name)
                )
                paragraphs: list[str] = []
                for part in parts:
                    paragraphs.extend(DocxParser.paragraphs(DocxParser._read(package, part)))
                images = DocxParser._images(package)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"not a valid .docx file: {exc}") from exc
        return "\n".join(paragraphs).strip(), images

    @staticmethod
    def _read(package: zipfile.ZipFile, name: str) -> bytes:
        info = package.getinfo(name)
        if info.file_size > DocxParser.MAX_XML_PART_BYTES:
            raise ValueError(f"{name} is too large to read ({info.file_size} bytes)")
        return package.read(name)

    @staticmethod
    def _images(package: zipfile.ZipFile, prefix: str = "word/media/") -> list[bytes]:
        def sort_key(name: str) -> list[object]:
            # image2 before image10
            return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]

        names = sorted(
            (
                name
                for name in package.namelist()
                if name.startswith(prefix) and name.lower().endswith(DocxParser.IMAGE_SUFFIXES)
            ),
            key=sort_key,
        )
        return DocxParser.read_images(package, names)

    @staticmethod
    def read_images(package: zipfile.ZipFile, names: list[str]) -> list[bytes]:
        """The raw bytes of the named package parts, skipping oversized and repeated ones."""
        images: list[bytes] = []
        seen: set[int] = set()
        for name in names:
            if package.getinfo(name).file_size > DocxParser.MAX_IMAGE_BYTES:
                _logger.warning("Skipping oversized embedded image %s", name)
                continue
            data = package.read(name)
            # The same picture is often referenced from several places (a logo in every
            # header); it only needs reading once.
            if hash(data) in seen:
                continue
            seen.add(hash(data))
            images.append(data)
        return images

    @staticmethod
    def paragraphs(xml: bytes) -> list[str]:
        """The non-empty paragraphs of a WordprocessingML part, in document order."""
        root = ElementTree.fromstring(xml)
        found: list[str] = []

        def walk(element: ElementTree.Element) -> None:
            # An AlternateContent block holds the same content twice (a modern
            # `Choice` and a legacy `Fallback`); reading both would double it.
            if element.tag == f"{DocxParser._MC}Fallback":
                return
            if element.tag == f"{DocxParser._W}p":
                text = DocxParser._paragraph_text(element)
                if text.strip():
                    found.append(text)
            for child in element:
                walk(child)

        walk(root)
        return found

    @staticmethod
    def _paragraph_text(paragraph: ElementTree.Element) -> str:
        w = DocxParser._W
        pieces: list[str] = []

        def walk(element: ElementTree.Element) -> None:
            for child in element:
                tag = child.tag
                # Text boxes hold their own paragraphs, which `paragraphs` visits itself.
                if tag in (f"{w}txbxContent", f"{DocxParser._MC}Fallback"):
                    continue
                if tag == f"{w}t":
                    pieces.append(child.text or "")
                elif tag == f"{w}tab":
                    pieces.append("\t")
                elif tag in (f"{w}br", f"{w}cr"):
                    pieces.append("\n")
                elif tag == f"{w}noBreakHyphen":
                    pieces.append("-")
                elif tag == f"{w}delText":
                    continue  # a tracked deletion
                else:
                    walk(child)

        walk(paragraph)
        return "".join(pieces)


class DocParser:
    """Reads text (and any PNG/JPEG pictures) out of a legacy Word 97-2003 `.doc` file.

    Best effort: the text comes from the document's piece table (MS-DOC 2.4.1); pictures
    are carved out of the file's OfficeArt BLIP records.
    """

    WORD_STREAM = "WordDocument"
    MAGIC = 0xA5EC
    ENCRYPTED = 0x0100
    TABLE_STREAM_1 = 0x0200
    WORD97_NFIB = 0x00C1
    FC_CLX_OFFSET = 0x01A2  # FibRgFcLcb97.fcClx; lcbClx follows it
    COMPRESSED = 0x40000000

    # OfficeArt record types for a raw JPEG / PNG BLIP, and the record instances that
    # carry a second 16-byte UID ahead of the data.
    _JPEG_TYPES = {0xF01D, 0xF02A}
    _PNG_TYPE = 0xF01E
    _TWO_UID_INSTANCES = {0x46B, 0x6E3, 0x6E1}
    _MAX_PICTURE_BYTES = 64 * 1024 * 1024
    _BLIP_TYPE = re.compile(rb"[\x1d\x1e\x2a]\xf0")

    @staticmethod
    def extract(file_path: Path) -> tuple[str, list[bytes]]:
        import olefile

        if not olefile.isOleFile(str(file_path)):
            raise ValueError("not a valid .doc file (not an OLE compound file)")
        with olefile.OleFileIO(str(file_path)) as ole:
            if not ole.exists(DocParser.WORD_STREAM):
                raise ValueError("not a Word document: no WordDocument stream")
            word = ole.openstream(DocParser.WORD_STREAM).read()
            text = DocParser.text(word, lambda name: DocParser._stream(ole, name))
            images = DocParser._pictures(ole, word)
        return text, images

    @staticmethod
    def _stream(ole, name: str) -> bytes | None:
        return ole.openstream(name).read() if ole.exists(name) else None

    @staticmethod
    def text(word: bytes, table_stream) -> str:
        """The document text, given the `WordDocument` stream and a `name -> bytes|None`
        lookup for the table streams."""
        if len(word) < 0x20 or struct.unpack_from("<H", word, 0)[0] != DocParser.MAGIC:
            raise ValueError("not a Word document: bad FIB signature")
        (n_fib,) = struct.unpack_from("<H", word, 2)
        (flags,) = struct.unpack_from("<H", word, 0x0A)
        if flags & DocParser.ENCRYPTED:
            raise ValueError("password-protected .doc files are not supported")

        if n_fib < DocParser.WORD97_NFIB:
            # Word 6/95: the text is one contiguous 8-bit run between fcMin and fcMac.
            fc_min, fc_mac = struct.unpack_from("<II", word, 0x18)
            return DocParser.clean(word[fc_min:fc_mac].decode("cp1252", errors="replace"))

        fc_clx, lcb_clx = struct.unpack_from("<II", word, DocParser.FC_CLX_OFFSET)
        name = "1Table" if flags & DocParser.TABLE_STREAM_1 else "0Table"
        table = table_stream(name)
        if table is None:
            raise ValueError(f"corrupt .doc: missing {name} stream")
        clx = table[fc_clx : fc_clx + lcb_clx]
        return DocParser.clean(DocParser._piece_text(word, clx))

    @staticmethod
    def _piece_text(word: bytes, clx: bytes) -> str:
        position = 0
        # Skip the Prc entries (property modifiers) ahead of the piece table.
        while position < len(clx) and clx[position] == 0x01:
            (size,) = struct.unpack_from("<H", clx, position + 1)
            position += 3 + size
        if position >= len(clx) or clx[position] != 0x02:
            raise ValueError("corrupt .doc: piece table not found")
        (size,) = struct.unpack_from("<I", clx, position + 1)
        plc = clx[position + 5 : position + 5 + size]

        count = (len(plc) - 4) // 12  # n+1 character positions (4 bytes), n PCDs (8 bytes)
        if count <= 0:
            return ""
        cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
        pieces: list[str] = []
        for index in range(count):
            (fc,) = struct.unpack_from("<I", plc, (count + 1) * 4 + index * 8 + 2)
            length = cps[index + 1] - cps[index]
            if fc & DocParser.COMPRESSED:
                start = (fc & ~DocParser.COMPRESSED) // 2
                raw = word[start : start + length]
                pieces.append(raw.decode("cp1252", errors="replace"))
            else:
                raw = word[fc : fc + length * 2]
                pieces.append(raw.decode("utf-16-le", errors="replace"))
        return "".join(pieces)

    @staticmethod
    def clean(raw: str) -> str:
        """Turn Word's control characters into plain text.

        Field codes (`\\x13 CODE \\x14 result \\x15`) keep only their result; paragraph
        and cell/row marks become line/tab breaks; picture and drawing anchors vanish.
        """
        out: list[str] = []
        # For each open field: whether we're still inside its code (before the \x14).
        fields: list[bool] = []
        for char in raw:
            if char == "\x13":
                fields.append(True)
            elif char == "\x14":
                if fields:
                    fields[-1] = False
            elif char == "\x15":
                if fields:
                    fields.pop()
            elif any(fields):
                continue
            elif char in "\r\x0b\x0c":
                out.append("\n")
            elif char == "\x07":
                out.append("\t")
            elif char == "\x1e":
                out.append("-")
            elif char == "\t" or char == "\n" or char >= " ":
                out.append(char)
        lines = (line.strip(" \t") for line in "".join(out).split("\n"))
        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def _pictures(ole, word: bytes) -> list[bytes]:
        pictures: list[bytes] = []
        seen: set[int] = set()
        try:
            streams = [word]
            if ole.exists("Data"):
                streams.append(ole.openstream("Data").read())
            for stream in streams:
                for data in DocParser.carve_pictures(stream):
                    if hash(data) not in seen:
                        seen.add(hash(data))
                        pictures.append(data)
        except Exception:  # noqa: BLE001 - pictures are a bonus; never fail the text over them
            _logger.warning("Could not read embedded pictures", exc_info=True)
        return pictures

    @staticmethod
    def carve_pictures(stream: bytes) -> list[bytes]:
        """JPEG/PNG data from the OfficeArt BLIP records found in `stream`."""
        found: list[bytes] = []
        position = 0
        while (hit := DocParser._next_blip(stream, position)) is not None:
            start, end = hit
            found.append(stream[start:end])
            position = end
        return found

    @staticmethod
    def _next_blip(stream: bytes, position: int) -> tuple[int, int] | None:
        """The `(start, end)` of the next valid raw JPEG/PNG BLIP at/after `position`.

        A BLIP record header is recVer/recInstance (2 bytes), recType (2), recLen (4);
        recVer is 0 for a BLIP. The picture follows one or two 16-byte UIDs and a
        1-byte tag. Every candidate is checked against the image's own signature, so a
        stray `\\xf0` byte pair in other data is skipped rather than carved.
        """
        size = len(stream)
        for match in DocParser._BLIP_TYPE.finditer(stream, position + 2):
            header = match.start() - 2
            if header < position or stream[header] & 0x0F or header + 8 > size:
                continue
            ver_inst, rec_type, rec_len = struct.unpack_from("<HHI", stream, header)
            if rec_len > DocParser._MAX_PICTURE_BYTES or header + 8 + rec_len > size:
                continue
            uid_bytes = 32 if (ver_inst >> 4) in DocParser._TWO_UID_INSTANCES else 16
            data_start = header + 8 + uid_bytes + 1
            signature = stream[data_start : data_start + 8]
            is_png = rec_type == DocParser._PNG_TYPE
            if is_png and signature == b"\x89PNG\r\n\x1a\n":
                return data_start, header + 8 + rec_len
            if not is_png and signature[:3] == b"\xff\xd8\xff":
                return data_start, header + 8 + rec_len
        return None


class Excel:
    """Pieces shared by the `.xlsx` and `.xls` parsers: how a cell's value becomes text."""

    # Built-in number formats that are dates and/or times (ECMA-376 18.8.30).
    _BUILTIN_DATE_FORMATS = frozenset({*range(14, 23), *range(27, 37), *range(45, 48)}) | frozenset(
        range(50, 59)
    )
    _QUOTED_OR_ESCAPED = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.')
    _DATE_TOKEN = re.compile(r"[dmyhs]", re.IGNORECASE)

    @staticmethod
    def is_date_format(format_id: int, format_code: str | None) -> bool:
        if format_code is None:
            return format_id in Excel._BUILTIN_DATE_FORMATS
        return bool(Excel._DATE_TOKEN.search(Excel._QUOTED_OR_ESCAPED.sub("", format_code)))

    @staticmethod
    def number(value: float | str) -> str:
        """A number the way Excel's General format shows it: no trailing `.0`, no float noise."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number != number or number in (float("inf"), float("-inf")):
            return str(value)
        if number.is_integer() and abs(number) < 1e15:
            return str(int(number))
        return f"{number:.15g}"

    @staticmethod
    def date(serial: float | str, *, date1904: bool) -> str:
        """An Excel date serial as `YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS` or `HH:MM:SS`.

        Falls back to the plain number if it isn't a representable date.
        """
        try:
            value = float(serial)
            if value < 0:
                raise ValueError
            # 1900 mode counts a leap day that never existed (serial 60), so serials
            # from 61 on map to a 1899-12-30 epoch and the few before it to 12-31.
            epoch = (
                datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30 if value >= 61 else 31)
            )
            moment = epoch + timedelta(seconds=round(value * 86400))
        except (ValueError, OverflowError):
            return Excel.number(serial)
        if value < 1:
            return moment.strftime("%H:%M:%S")
        if moment.hour == moment.minute == moment.second == 0:
            return moment.strftime("%Y-%m-%d")
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def sheet_text(name: str, rows: Iterator[str]) -> str:
        """`name` followed by the sheet's non-empty rows; empty if the sheet holds nothing."""
        lines = [row for row in rows if row]
        return "\n".join([name, *lines]) if lines else ""


class XlsxParser:
    """Reads text (and embedded pictures) out of an Excel `.xlsx` workbook.

    Each sheet becomes its name followed by one line per row, cells tab-separated.
    Formulas contribute the value Excel last calculated; dates are shown as dates
    rather than serial numbers. Cell comments and text boxes follow the sheets.
    """

    # Parts are streamed rather than loaded whole, but a hostile file could still claim
    # an absurd uncompressed size.
    MAX_XML_PART_BYTES = DocxParser.MAX_XML_PART_BYTES

    _COMMENTS_PART = re.compile(r"^xl/comments\d*\.xml$")
    _DRAWING_PART = re.compile(r"^xl/drawings/drawing\d*\.xml$")
    _OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    @staticmethod
    def extract(file_path: Path) -> tuple[str, list[bytes]]:
        """Return `(text, images)`: the workbook's text, and its raster images' raw bytes."""
        try:
            with zipfile.ZipFile(file_path) as package:
                names = set(package.namelist())
                if "xl/workbook.xml" not in names:
                    raise ValueError("not an Excel workbook: xl/workbook.xml is missing")
                shared = (
                    XlsxParser._shared_strings(package) if "xl/sharedStrings.xml" in names else []
                )
                date_styles = (
                    XlsxParser._date_styles(package) if "xl/styles.xml" in names else set()
                )
                sheets, date1904 = XlsxParser._sheets(package, names)
                blocks = [
                    Excel.sheet_text(
                        name, XlsxParser._rows(package, part, shared, date_styles, date1904)
                    )
                    for name, part in sheets
                ]
                blocks.extend(XlsxParser._notes(package, sorted(names)))
                images = DocxParser._images(package, "xl/media/")
        except zipfile.BadZipFile as exc:
            if XlsxParser._is_ole(file_path):
                raise ValueError(
                    "not a valid .xlsx file: it is password-protected or in an older format"
                ) from exc
            raise ValueError(f"not a valid .xlsx file: {exc}") from exc
        return "\n".join(block for block in blocks if block).strip(), images

    @staticmethod
    def _is_ole(file_path: Path) -> bool:
        with open(file_path, "rb") as handle:
            return handle.read(8) == XlsxParser._OLE_MAGIC

    @staticmethod
    def _local(tag: str) -> str:
        """An element's name without its namespace (the strict and transitional
        spreadsheet namespaces differ, the element names don't)."""
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _open(package: zipfile.ZipFile, name: str):
        size = package.getinfo(name).file_size
        if size > XlsxParser.MAX_XML_PART_BYTES:
            raise ValueError(f"{name} is too large to read ({size} bytes)")
        return package.open(name)

    @staticmethod
    def _text(element: ElementTree.Element) -> str:
        """The text of a string item: its `<t>` runs, but not the phonetic (`rPh`) ones."""
        local = XlsxParser._local
        pieces: list[str] = []
        for child in element:
            if local(child.tag) == "t":
                pieces.append(child.text or "")
            elif local(child.tag) == "r":
                pieces.extend((sub.text or "") for sub in child if local(sub.tag) == "t")
        return "".join(pieces)

    @staticmethod
    def _shared_strings(package: zipfile.ZipFile) -> list[str]:
        strings: list[str] = []
        with XlsxParser._open(package, "xl/sharedStrings.xml") as handle:
            for _, element in ElementTree.iterparse(handle):
                if XlsxParser._local(element.tag) == "si":
                    strings.append(XlsxParser._text(element))
                    element.clear()
        return strings

    @staticmethod
    def _date_styles(package: zipfile.ZipFile) -> set[int]:
        """The indexes of the cell formats (`cellXfs`) that display a date or time."""
        local = XlsxParser._local
        with XlsxParser._open(package, "xl/styles.xml") as handle:
            root = ElementTree.parse(handle).getroot()
        codes: dict[int, str] = {}
        date_styles: set[int] = set()
        for section in root:
            if local(section.tag) == "numFmts":
                for fmt in section:
                    declared = fmt.get("numFmtId", "")
                    if declared.isdigit():
                        codes[int(declared)] = fmt.get("formatCode", "")
            elif local(section.tag) == "cellXfs":
                for index, xf in enumerate(section):
                    format_id = int(xf.get("numFmtId", "0") or 0)
                    if Excel.is_date_format(format_id, codes.get(format_id)):
                        date_styles.add(index)
        return date_styles

    @staticmethod
    def _sheets(package: zipfile.ZipFile, names: set[str]) -> tuple[list[tuple[str, str]], bool]:
        """`([(sheet name, part name), ...] in workbook order, uses the 1904 date system)`."""
        local = XlsxParser._local
        with XlsxParser._open(package, "xl/workbook.xml") as handle:
            root = ElementTree.parse(handle).getroot()

        targets: dict[str, str] = {}
        rels = "xl/_rels/workbook.xml.rels"
        if rels in names:
            with XlsxParser._open(package, rels) as handle:
                for rel in ElementTree.parse(handle).getroot():
                    target = rel.get("Target", "")
                    # Targets are relative to xl/, or absolute from the package root.
                    targets[rel.get("Id", "")] = (
                        target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                    )

        date1904 = False
        sheets: list[tuple[str, str]] = []
        for section in root:
            if local(section.tag) == "workbookPr":
                date1904 = section.get("date1904", "0").lower() in ("1", "true")
            elif local(section.tag) == "sheets":
                for sheet in section:
                    rel_id = next(
                        (value for key, value in sheet.attrib.items() if key.endswith("}id")), ""
                    )
                    part = targets.get(rel_id)
                    if part in names:
                        sheets.append((sheet.get("name", ""), part))
        if not sheets:
            # No usable relationships: fall back to the worksheet parts in numeric order.
            def order(name: str) -> int:
                return int(re.sub(r"\D", "", name) or 0)

            parts = sorted(
                (n for n in names if re.match(r"^xl/worksheets/[^/]+\.xml$", n)), key=order
            )
            sheets = [(f"Sheet{i}", part) for i, part in enumerate(parts, start=1)]
        return sheets, date1904

    @staticmethod
    def _rows(
        package: zipfile.ZipFile,
        part: str,
        shared: list[str],
        date_styles: set[int],
        date1904: bool,
    ) -> Iterator[str]:
        """One tab-separated line per row of a worksheet part, streamed."""
        local = XlsxParser._local
        row: list[str] = []
        with XlsxParser._open(package, part) as handle:
            for _, element in ElementTree.iterparse(handle):
                tag = local(element.tag)
                if tag == "c":
                    value = XlsxParser._cell(element, shared, date_styles, date1904)
                    if value:
                        row.append(value)
                elif tag == "row":
                    yield "\t".join(row)
                    row = []
                    element.clear()
        if row:
            yield "\t".join(row)

    @staticmethod
    def _cell(
        cell: ElementTree.Element, shared: list[str], date_styles: set[int], date1904: bool
    ) -> str:
        local = XlsxParser._local
        kind = cell.get("t", "n")
        raw = ""
        inline = ""
        for child in cell:
            if local(child.tag) == "v":
                raw = child.text or ""
            elif local(child.tag) == "is":
                inline = XlsxParser._text(child)
        if kind == "inlineStr":
            return inline.strip()
        if not raw:
            return ""
        if kind == "s":
            try:
                return shared[int(raw)].strip()
            except (ValueError, IndexError):
                return ""
        if kind == "b":
            return "TRUE" if raw.strip() == "1" else "FALSE"
        if kind == "e":
            return ""  # #N/A, #REF! ... carry no content
        if kind in ("str", "d"):
            return raw.strip()
        if int(cell.get("s", "0") or 0) in date_styles:
            return Excel.date(raw, date1904=date1904)
        return Excel.number(raw)

    @staticmethod
    def _notes(package: zipfile.ZipFile, names: list[str]) -> list[str]:
        """Cell comments and drawing text boxes, which sit outside the cell grid."""
        local = XlsxParser._local
        notes: list[str] = []
        for name in names:
            if XlsxParser._COMMENTS_PART.match(name):
                with XlsxParser._open(package, name) as handle:
                    root = ElementTree.parse(handle).getroot()
                for element in root.iter():
                    if local(element.tag) == "text":
                        text = " ".join(XlsxParser._text(element).split())
                        if text:
                            notes.append(text)
            elif XlsxParser._DRAWING_PART.match(name):
                with XlsxParser._open(package, name) as handle:
                    root = ElementTree.parse(handle).getroot()
                for paragraph in root.iter():
                    if local(paragraph.tag) == "p":
                        text = "".join(
                            node.text or "" for node in paragraph.iter() if local(node.tag) == "t"
                        ).strip()
                        if text:
                            notes.append(text)
        return notes


class XlsParser:
    """Reads text (and any PNG/JPEG pictures) out of a legacy Excel 97-2003 `.xls` file.

    Cell values come from `xlrd`, which reads the BIFF records. Pictures are best effort:
    they're carved out of the OfficeArt BLIP records in the workbook's drawing group,
    the same way `DocParser` does for Word.
    """

    WORKBOOK_STREAMS = ("Workbook", "Book")

    # BIFF record types.
    _EOF = 0x000A
    _CONTINUE = 0x003C
    _MSO_DRAWING_GROUP = 0x00EB

    @staticmethod
    def extract(file_path: Path) -> tuple[str, list[bytes]]:
        return XlsParser.text(file_path), XlsParser._pictures(file_path)

    @staticmethod
    def text(file_path: Path) -> str:
        import xlrd

        try:
            book = xlrd.open_workbook(str(file_path), on_demand=True, logfile=io.StringIO())
        except xlrd.XLRDError as exc:
            if "encrypted" in str(exc).lower():
                raise ValueError("password-protected .xls files are not supported") from exc
            raise ValueError(f"not a valid .xls file: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - xlrd lets struct/index errors through on corrupt files
            raise ValueError(f"corrupt .xls file: {exc}") from exc

        try:
            blocks = []
            for index in range(book.nsheets):
                sheet = book.sheet_by_index(index)
                blocks.append(
                    Excel.sheet_text(
                        sheet.name, (XlsParser._row(book, sheet, row) for row in range(sheet.nrows))
                    )
                )
                book.unload_sheet(index)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"corrupt .xls file: {exc}") from exc
        finally:
            book.release_resources()
        return "\n".join(block for block in blocks if block).strip()

    @staticmethod
    def _row(book, sheet, row_index: int) -> str:
        import xlrd

        cells: list[str] = []
        for cell in sheet.row(row_index):
            if cell.ctype == xlrd.XL_CELL_TEXT:
                value = str(cell.value).strip()
            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                value = Excel.number(cell.value)
            elif cell.ctype == xlrd.XL_CELL_DATE:
                value = Excel.date(cell.value, date1904=book.datemode == 1)
            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                value = "TRUE" if cell.value else "FALSE"
            else:
                value = ""  # empty, blank or an error value
            if value:
                cells.append(value)
        return "\t".join(cells)

    @staticmethod
    def _pictures(file_path: Path) -> list[bytes]:
        pictures: list[bytes] = []
        try:
            import olefile

            if not olefile.isOleFile(str(file_path)):
                return pictures
            with olefile.OleFileIO(str(file_path)) as ole:
                name = next((n for n in XlsParser.WORKBOOK_STREAMS if ole.exists(n)), None)
                if name is None:
                    return pictures
                group = XlsParser.drawing_group(ole.openstream(name).read())
            seen: set[int] = set()
            for data in DocParser.carve_pictures(group):
                if hash(data) not in seen:
                    seen.add(hash(data))
                    pictures.append(data)
        except Exception:  # noqa: BLE001 - pictures are a bonus; never fail the text over them
            _logger.warning("Could not read embedded pictures", exc_info=True)
        return pictures

    @staticmethod
    def drawing_group(stream: bytes) -> bytes:
        """The workbook's MSODRAWINGGROUP record data, with its CONTINUE records joined on.

        BIFF splits any record longer than 8224 bytes across CONTINUE records, which would
        cut every large picture in two (and leave a record header in its middle).
        Only the globals substream (up to its first EOF) holds the group.
        """
        chunks: list[bytes] = []
        in_group = False
        position = 0
        while position + 4 <= len(stream):
            record_type, length = struct.unpack_from("<HH", stream, position)
            body = stream[position + 4 : position + 4 + length]
            position += 4 + length
            if record_type == XlsParser._EOF:
                break
            if record_type == XlsParser._MSO_DRAWING_GROUP:
                in_group = True
                chunks.append(body)
            elif record_type == XlsParser._CONTINUE and in_group:
                chunks.append(body)
            else:
                in_group = False
        return b"".join(chunks)


class PptxParser:
    """Reads text (and embedded pictures) out of a PowerPoint `.pptx` presentation.

    Slides come first in presentation order (titles, text boxes, grouped shapes, and tables
    with one line per row, cells tab-separated), then each slide's speaker notes, then
    comments and SmartArt text. Slide masters and layouts are boilerplate and are skipped,
    along with the pictures only they use.
    """

    MAX_XML_PART_BYTES = DocxParser.MAX_XML_PART_BYTES

    _SLIDE_PART = re.compile(r"^ppt/slides/slide\d+\.xml$")
    _NOTES_PART = re.compile(r"^ppt/notesSlides/notesSlide\d+\.xml$")
    _COMMENT_PART = re.compile(r"^ppt/comments/[^/]+\.xml$")
    _DIAGRAM_PART = re.compile(r"^ppt/diagrams/data\d*\.xml$")

    @staticmethod
    def extract(file_path: Path) -> tuple[str, list[bytes]]:
        """Return `(text, images)`: the presentation's text, and its raster images' bytes."""
        try:
            with zipfile.ZipFile(file_path) as package:
                names = set(package.namelist())
                if "ppt/presentation.xml" not in names:
                    raise ValueError(
                        "not a PowerPoint presentation: ppt/presentation.xml is missing"
                    )
                blocks: list[str] = []
                notes: list[str] = []
                image_parts: list[str] = []
                for slide in PptxParser._slides(package, names):
                    blocks.append(
                        "\n".join(PptxParser.paragraphs(DocxParser._read(package, slide)))
                    )
                    for kind, part in PptxParser._relationships(package, slide, names):
                        if kind == "notesSlide" and part not in notes:
                            notes.append(part)
                        elif kind == "image":
                            image_parts.append(part)
                notes.extend(
                    sorted(
                        (n for n in names if PptxParser._NOTES_PART.match(n) and n not in notes),
                        key=PptxParser._natural,
                    )
                )
                for part in notes:
                    blocks.append("\n".join(PptxParser.notes(DocxParser._read(package, part))))
                    image_parts.extend(
                        target
                        for kind, target in PptxParser._relationships(package, part, names)
                        if kind == "image"
                    )
                for name in sorted(names, key=PptxParser._natural):
                    if PptxParser._COMMENT_PART.match(name):
                        blocks.extend(PptxParser.comments(DocxParser._read(package, name)))
                    elif PptxParser._DIAGRAM_PART.match(name):
                        blocks.extend(PptxParser.paragraphs(DocxParser._read(package, name)))
                images = DocxParser.read_images(package, list(dict.fromkeys(image_parts)))
        except zipfile.BadZipFile as exc:
            if XlsxParser._is_ole(file_path):
                raise ValueError(
                    "not a valid .pptx file: it is password-protected or in an older format"
                ) from exc
            raise ValueError(f"not a valid .pptx file: {exc}") from exc
        return "\n".join(block for block in blocks if block).strip(), images

    @staticmethod
    def _natural(name: str) -> list[object]:
        # slide2 before slide10
        return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]

    @staticmethod
    def _local(tag: str) -> str:
        """An element's name without its namespace (the strict and transitional
        presentation namespaces differ, the element names don't)."""
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _slides(package: zipfile.ZipFile, names: set[str]) -> list[str]:
        """Slide parts in presentation order; any the slide list leaves out follow by number."""
        ordered: list[str] = []
        try:
            targets = {
                rel_id: part
                for rel_id, _, part in PptxParser._relationship_entries(
                    package, "ppt/presentation.xml", names
                )
            }
            root = ElementTree.fromstring(DocxParser._read(package, "ppt/presentation.xml"))
            for element in root.iter():
                if PptxParser._local(element.tag) != "sldId":
                    continue
                rel_id = next(
                    (v for k, v in element.attrib.items() if k.endswith("}id")),
                    None,
                )
                part = targets.get(rel_id or "")
                if part in names and PptxParser._SLIDE_PART.match(part) and part not in ordered:
                    ordered.append(part)
        except ElementTree.ParseError:
            _logger.warning("Could not read the slide order; using file order", exc_info=True)
        rest = (n for n in names if PptxParser._SLIDE_PART.match(n) and n not in ordered)
        return ordered + sorted(rest, key=PptxParser._natural)

    @staticmethod
    def _relationship_entries(
        package: zipfile.ZipFile, part: str, names: set[str]
    ) -> list[tuple[str, str, str]]:
        """`(id, type, target part)` for each internal relationship of `part`."""
        directory, _, name = part.rpartition("/")
        rels = f"{directory}/_rels/{name}.rels"
        if rels not in names:
            return []
        try:
            root = ElementTree.fromstring(DocxParser._read(package, rels))
        except ElementTree.ParseError:
            return []
        entries: list[tuple[str, str, str]] = []
        for rel in root:
            target = rel.get("Target")
            if not target or rel.get("TargetMode") == "External":
                continue
            resolved = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join(directory, target))
            )
            entries.append((rel.get("Id", ""), rel.get("Type", ""), resolved))
        return entries

    @staticmethod
    def _relationships(
        package: zipfile.ZipFile, part: str, names: set[str]
    ) -> list[tuple[str, str]]:
        """`(kind, target part)` for the notes and pictures `part` points to, where kind is
        the last segment of the relationship type (`notesSlide`, `image`)."""
        return [
            (rel_type.rsplit("/", 1)[-1], target)
            for _, rel_type, target in PptxParser._relationship_entries(package, part, names)
            if target in names
        ]

    @staticmethod
    def paragraphs(xml: bytes) -> list[str]:
        """The non-empty paragraphs of a PresentationML part, in document order. A table
        row is one line, its cells tab-separated."""
        return PptxParser._paragraphs_in(ElementTree.fromstring(xml))

    @staticmethod
    def _paragraphs_in(root: ElementTree.Element) -> list[str]:
        local = PptxParser._local
        found: list[str] = []

        def walk(element: ElementTree.Element) -> None:
            tag = local(element.tag)
            # An AlternateContent block holds the same content twice (a modern `Choice`
            # and a legacy `Fallback`); reading both would double it.
            if tag == "Fallback":
                return
            if tag == "p":
                text = PptxParser._paragraph_text(element)
                if text.strip():
                    found.append(text)
                return
            if tag == "tbl":
                for row in element:
                    if local(row.tag) != "tr":
                        continue
                    cells = [
                        " ".join(" ".join(PptxParser._paragraphs_in(cell)).split())
                        for cell in row
                        if local(cell.tag) == "tc"
                    ]
                    if any(cells):
                        found.append("\t".join(cells))
                return
            for child in element:
                walk(child)

        walk(root)
        return found

    @staticmethod
    def _paragraph_text(paragraph: ElementTree.Element) -> str:
        local = PptxParser._local
        pieces: list[str] = []

        def walk(element: ElementTree.Element) -> None:
            for child in element:
                tag = local(child.tag)
                if tag == "t":
                    pieces.append(child.text or "")
                elif tag == "br":
                    pieces.append("\n")
                elif tag == "fld" and (child.get("type") or "").startswith("slidenum"):
                    continue  # the slide's own number, not content
                elif tag in ("rPr", "pPr", "endParaRPr"):
                    continue
                else:
                    walk(child)

        walk(paragraph)
        return "".join(pieces)

    @staticmethod
    def notes(xml: bytes) -> list[str]:
        """The speaker-notes text of a notes slide: its body placeholder only, not the
        slide thumbnail, slide number or header/footer placeholders."""
        local = PptxParser._local
        found: list[str] = []
        for shape in ElementTree.fromstring(xml).iter():
            if local(shape.tag) != "sp":
                continue
            placeholder = next((e for e in shape.iter() if local(e.tag) == "ph"), None)
            if placeholder is not None and placeholder.get("type") == "body":
                found.extend(PptxParser._paragraphs_in(shape))
        return found

    @staticmethod
    def comments(xml: bytes) -> list[str]:
        """Comment text from a legacy (`<p:text>`) or modern (`<p188:txBody>`, replies
        included) comment part."""
        local = PptxParser._local
        found: list[str] = []
        for comment in ElementTree.fromstring(xml).iter():
            if local(comment.tag) != "cm":
                continue
            for child in comment:
                if local(child.tag) == "text":
                    text = " ".join((child.text or "").split())
                    if text:
                        found.append(text)
            found.extend(PptxParser._paragraphs_in(comment))
        return found


class PptParser:
    """Reads text (and any PNG/JPEG pictures) out of a legacy PowerPoint 97-2003 `.ppt` file.

    Best effort: text comes from the text atoms (MS-PPT `TextCharsAtom`/`TextBytesAtom`) in
    the `PowerPoint Document` stream's record tree, skipping slide masters; pictures are
    carved out of the `Pictures` stream's OfficeArt BLIP records.
    """

    DOCUMENT_STREAM = "PowerPoint Document"
    PICTURES_STREAM = "Pictures"
    ENCRYPTED_STREAM = "EncryptedSummary"

    # Record types (MS-PPT 2.13.24). A record header is recVer/recInstance (2 bytes),
    # recType (2), recLen (4); recVer 0xF marks a container.
    _TEXT_CHARS = 0x0FA0  # UTF-16LE
    _TEXT_BYTES = 0x0FA8  # one byte per character
    _MAIN_MASTER = 0x03F8
    _HANDOUT = 0x0FC9
    _SLIDE_LIST = 0x0FF0  # instance 1 is the masters' text
    _CRYPT_SESSION = 0x2F14
    _CONTAINER = 0x0F
    _MAX_DEPTH = 32

    _CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")

    @staticmethod
    def extract(file_path: Path) -> tuple[str, list[bytes]]:
        import olefile

        if not olefile.isOleFile(str(file_path)):
            raise ValueError("not a valid .ppt file (not an OLE compound file)")
        try:
            with olefile.OleFileIO(str(file_path)) as ole:
                if not ole.exists(PptParser.DOCUMENT_STREAM):
                    raise ValueError("not a PowerPoint presentation: no PowerPoint Document stream")
                if ole.exists(PptParser.ENCRYPTED_STREAM):
                    raise ValueError("password-protected .ppt files are not supported")
                stream = ole.openstream(PptParser.DOCUMENT_STREAM).read()
                images = PptParser._pictures(ole)
        except OSError as exc:
            raise ValueError(f"not a valid .ppt file: {exc}") from exc
        return PptParser.text(stream), images

    @staticmethod
    def text(stream: bytes) -> str:
        """The text of every slide and notes page in a `PowerPoint Document` stream."""
        blocks: list[str] = []
        PptParser._walk(stream, 0, len(stream), blocks, depth=0)
        return "\n".join(blocks).strip()

    @staticmethod
    def _walk(stream: bytes, start: int, end: int, blocks: list[str], depth: int) -> None:
        position = start
        while position + 8 <= end:
            ver_inst, rec_type, length = struct.unpack_from("<HHI", stream, position)
            body = position + 8
            stop = body + length
            if stop > end:
                return  # truncated or corrupt: keep what was read so far
            if rec_type == PptParser._CRYPT_SESSION and depth == 0:
                raise ValueError("password-protected .ppt files are not supported")
            if ver_inst & 0x0F == PptParser._CONTAINER:
                masters_text = rec_type == PptParser._SLIDE_LIST and ver_inst >> 4 == 1
                skipped = rec_type in (PptParser._MAIN_MASTER, PptParser._HANDOUT) or masters_text
                if not skipped and depth < PptParser._MAX_DEPTH:
                    PptParser._walk(stream, body, stop, blocks, depth + 1)
            elif rec_type == PptParser._TEXT_CHARS:
                data = stream[body : stop - length % 2]
                PptParser._add(blocks, data.decode("utf-16-le", errors="replace"))
            elif rec_type == PptParser._TEXT_BYTES:
                PptParser._add(blocks, stream[body:stop].decode("cp1252", errors="replace"))
            position = stop

    @staticmethod
    def _add(blocks: list[str], raw: str) -> None:
        # \r ends a paragraph and \v is a soft line break; the other control codes are
        # field and layout markers.
        text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n")
        text = PptParser._CONTROL.sub("", text).replace("�", "")
        lines = (line.strip(" \t") for line in text.split("\n"))
        text = "\n".join(line for line in lines if line)
        if text:
            blocks.append(text)

    @staticmethod
    def _pictures(ole) -> list[bytes]:
        pictures: list[bytes] = []
        seen: set[int] = set()
        try:
            if ole.exists(PptParser.PICTURES_STREAM):
                stream = ole.openstream(PptParser.PICTURES_STREAM).read()
                for data in DocParser.carve_pictures(stream):
                    if hash(data) not in seen:
                        seen.add(hash(data))
                        pictures.append(data)
        except Exception:  # noqa: BLE001 - pictures are a bonus; never fail the text over them
            _logger.warning("Could not read embedded pictures", exc_info=True)
        return pictures
