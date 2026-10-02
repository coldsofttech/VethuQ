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
