"""Pulling text and embedded images out of Word files, with no OCR and no database.

`DocxParser` reads the Office Open XML package directly (it's a zip of XML parts), so
it needs nothing beyond the standard library. `DocParser` reads the legacy binary
format (an OLE compound file) through `olefile`.
"""

from __future__ import annotations

import logging
import re
import struct
import zipfile
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
    def _images(package: zipfile.ZipFile) -> list[bytes]:
        def sort_key(name: str) -> list[object]:
            # image2 before image10
            return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]

        names = sorted(
            (
                name
                for name in package.namelist()
                if name.startswith("word/media/")
                and name.lower().endswith(DocxParser.IMAGE_SUFFIXES)
            ),
            key=sort_key,
        )
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
