"""A word-processor document (Word, RTF, OpenDocument text) made into blocks for the Word preview.

The preview shows a document the way a reader would (headings, lists, tables), but its match has to
be found in the text the index kept: the document's paragraphs, one a line. So the blocks are that
stored text, line by line, each with its offset, and the document's own structure is laid over them
where the file gives it (the style of a Word paragraph, the headings, lists and tables of an
OpenDocument file). The structure is read the way the DOCX and ODT add-ons read the text, and a line
it does not find a paragraph for (a legacy `.doc`, an `.rtf`, text read from a picture) is plain.
Nothing is run, and a file that cannot be read for its structure is shown as plain lines.
"""

from __future__ import annotations

import os
import re
import threading
import zipfile
from typing import Any
from xml.etree.ElementTree import Element

MAX_PART_BYTES = 128 * 1024 * 1024
MAX_DEPTH = 200
MAX_REPEAT = 50
MAX_BLOCKS = 1500
LINE_CLIP = 20_000
LOOKAHEAD = 8
KEEP_FILES = 2

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_EXTRA_PART = re.compile(r"^word/(header|footer)\d*\.xml$|^word/(footnotes|endnotes)\.xml$")
_HEADING = re.compile(r"^heading\s*(\d)")

_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"

Item = dict[str, Any]


def _xml(data: bytes) -> Element:
    try:
        from defusedxml.ElementTree import fromstring  # noqa: PLC0415 - only for these documents
    except ImportError as error:  # pragma: no cover - the add-ons need defusedxml
        raise ValueError(
            "defusedxml is not installed, so a document cannot be shown here."
        ) from error
    return fromstring(data)


def _read(package: zipfile.ZipFile, name: str) -> bytes:
    if package.getinfo(name).file_size > MAX_PART_BYTES:
        raise ValueError(f"{name} is too large to read")
    return package.read(name)


def _item(kind: str, text: str, **more: Any) -> Item:
    first = text.split("\n", 1)[0].strip()
    return {"kind": kind, "first": first, **more}


# ----- Word (.docx, .dotx) ----------------------------------------------------------------------


def _docx_styles(package: zipfile.ZipFile) -> dict[str, str]:
    """Style id -> the style's lowercase name (`heading 1`), so a renamed or translated id still
    reads as what it is."""
    if "word/styles.xml" not in package.namelist():
        return {}
    found = {}
    for style in _xml(_read(package, "word/styles.xml")).iter(_W + "style"):
        name = style.find(_W + "name")
        style_id = style.get(_W + "styleId")
        if style_id and name is not None:
            found[style_id] = (name.get(_W + "val") or "").lower()
    return found


def _docx_text(paragraph: Element) -> str:
    pieces: list[str] = []

    def walk(element: Element) -> None:
        for child in element:
            tag = child.tag
            if tag in (_W + "txbxContent", _MC + "Fallback"):
                continue
            if tag == _W + "t":
                pieces.append(child.text or "")
            elif tag == _W + "tab":
                pieces.append("\t")
            elif tag in (_W + "br", _W + "cr"):
                pieces.append("\n")
            elif tag == _W + "noBreakHyphen":
                pieces.append("-")
            elif tag == _W + "delText":
                continue
            else:
                walk(child)

    walk(paragraph)
    return "".join(pieces)


def _docx_kind(paragraph: Element, styles: dict[str, str]) -> tuple[str, int | None]:
    properties = paragraph.find(_W + "pPr")
    if properties is None:
        return "text", None
    style = properties.find(_W + "pStyle")
    name = styles.get(style.get(_W + "val", ""), "") if style is not None else ""
    if not name and style is not None:
        name = (style.get(_W + "val") or "").lower()
    found = _HEADING.match(name)
    if found:
        return "heading", int(found.group(1))
    if name in ("title", "subtitle"):
        return "title", None
    outline = properties.find(_W + "outlineLvl")
    if outline is not None and (outline.get(_W + "val") or "").isdigit():
        level = int(outline.get(_W + "val", "0"))
        if level < 9:
            return "heading", level + 1
    numbering = properties.find(_W + "numPr")
    if numbering is not None or name.startswith("list"):
        level = numbering.find(_W + "ilvl") if numbering is not None else None
        raw = level.get(_W + "val", "0") if level is not None else "0"
        return "list", int(raw) if raw.isdigit() else 0
    return "text", None


def _docx_part(xml: bytes, styles: dict[str, str], items: list[Item], rows: list[int]) -> None:
    root = _xml(xml)

    def walk(element: Element, cell: tuple[int, int] | None, depth: int = 0) -> None:
        if element.tag == _MC + "Fallback" or depth > MAX_DEPTH:
            return
        if element.tag == _W + "tr":
            rows[0] += 1
            rows[1] = 0
        elif element.tag == _W + "tc":
            rows[1] += 1
            cell = (rows[0], rows[1])
        if element.tag == _W + "p":
            text = _docx_text(element)
            if text.strip():
                kind, level = _docx_kind(element, styles)
                more: dict[str, Any] = {}
                if level is not None:
                    more["level"] = level
                if cell is not None:
                    more["row"], more["cell"] = cell
                    kind = "cell" if kind == "text" else kind
                items.append(_item(kind, text, **more))
        for child in element:
            walk(child, cell, depth + 1)

    walk(root, None)


def _docx(path: str) -> list[Item]:
    with zipfile.ZipFile(path) as package:
        names = package.namelist()
        if "word/document.xml" not in names:
            return []
        styles = _docx_styles(package)
        parts = ["word/document.xml"] + sorted(n for n in names if _EXTRA_PART.match(n))
        items: list[Item] = []
        rows = [0, 0]
        for part in parts:
            _docx_part(_read(package, part), styles, items, rows)
        return items


# ----- OpenDocument text (.odt, .ott) -----------------------------------------------------------


def _odt_inline(element: Element, depth: int = 0) -> str:
    if depth > MAX_DEPTH:
        return ""
    out = [element.text or ""]
    for child in element:
        tag = child.tag
        if tag == _TEXT + "s":
            raw = child.get(_TEXT + "c", "1")
            out.append(" " * min(int(raw) if raw.isdigit() else 1, MAX_REPEAT))
        elif tag == _TEXT + "tab":
            out.append("\t")
        elif tag == _TEXT + "line-break":
            out.append("\n")
        elif tag in (_TEXT + "note", _DRAW + "frame", _TEXT + "bookmark", _TEXT + "bookmark-start"):
            pass
        else:
            out.append(_odt_inline(child, depth + 1))
        out.append(child.tail or "")
    return "".join(out)[:1_000_000]


def _repeats(element: Element, name: str) -> int:
    raw = element.get(_TABLE + name, "1")
    return min(int(raw), MAX_REPEAT) if raw.isdigit() and int(raw) > 0 else 1


def _odt_rows(table: Element, depth: int = 0) -> list[Element]:
    found: list[Element] = []
    if depth > MAX_DEPTH:
        return found
    for child in table:
        if child.tag == _TABLE + "table-row":
            found.append(child)
        elif child.tag in (
            _TABLE + "table-row-group",
            _TABLE + "table-header-rows",
            _TABLE + "table-rows",
        ):
            found.extend(_odt_rows(child, depth + 1))
    return found


def _odt_cell(cell: Element) -> str:
    shown = " ".join(item["text"] for item in _odt_blocks(cell, False)).strip()
    if shown:
        return shown
    value = cell.get(_OFFICE + "string-value") or cell.get(_OFFICE + "value")
    if value is None:
        value = cell.get(_OFFICE + "date-value") or cell.get(_OFFICE + "time-value")
    if value is None and cell.get(_OFFICE + "boolean-value") is not None:
        value = cell.get(_OFFICE + "boolean-value", "").upper()
    return (value or "").replace("T", " ", 1) if cell.get(_OFFICE + "date-value") else (value or "")


def _odt_blocks(element: Element, listed: bool, depth: int = 0) -> list[Item]:
    if depth > MAX_DEPTH:
        return []
    found: list[Item] = []
    for child in element:
        tag = child.tag
        if tag in (_TEXT + "p", _TEXT + "h"):
            line = _odt_inline(child).strip()
            if line:
                if tag == _TEXT + "h":
                    raw = child.get(_TEXT + "outline-level", "1")
                    found.append(
                        {
                            **_item("heading", line),
                            "text": line,
                            "level": int(raw) if raw.isdigit() else 1,
                        }
                    )
                else:
                    found.append({**_item("list" if listed else "text", line), "text": line})
            for note in child.iter(_TEXT + "note"):
                body = note.find(_TEXT + "note-body")
                if body is not None:
                    found.extend(_odt_blocks(body, False, depth + 1))
        elif tag == _TABLE + "table":
            for row in _odt_rows(child):
                cells: list[str] = []
                for cell in row:
                    if cell.tag != _TABLE + "table-cell":
                        continue
                    shown = _odt_cell(cell)
                    if shown:
                        cells.extend([shown] * _repeats(cell, "number-columns-repeated"))
                if cells:
                    text = "\t".join(cells)
                    found.extend(
                        [{**_item("row", text), "text": text}]
                        * _repeats(row, "number-rows-repeated")
                    )
        elif tag in (
            _OFFICE + "scripts",
            _OFFICE + "forms",
            _TEXT + "tracked-changes",
            _TEXT + "sequence-decls",
        ):
            continue
        else:
            found.extend(_odt_blocks(child, listed or tag == _TEXT + "list-item", depth + 1))
    return found


def _odt(path: str) -> list[Item]:
    with zipfile.ZipFile(path) as package:
        if "content.xml" not in package.namelist():
            return []
        root = _xml(_read(package, "content.xml"))
    body = root.find(_OFFICE + "body")
    document = body.find(_OFFICE + "text") if body is not None else None
    return _odt_blocks(document, False) if document is not None else []


# ----- laying it out ----------------------------------------------------------------------------


def structure(path: str, kind: str) -> list[Item]:
    """The paragraphs of the document at `path` with what the file says they are, in the order the
    add-on reads them; empty when the file gives no structure (or cannot be read for it)."""
    try:
        if kind in ("docx", "dotx"):
            return _docx(path)
        if kind in ("odt", "ott"):
            return _odt(path)
    except Exception:  # noqa: BLE001 - the structure is a bonus: the text is shown without it
        return []
    return []


def layout(text: str, items: list[Item]) -> list[dict[str, Any]]:
    """The stored `text` as blocks `{text, start, kind, ...}`, `start` being the offset in `text`.
    A line takes the kind of the next paragraph (within a few) whose first line it is."""
    blocks = []
    offset = 0
    at = 0
    for line in text.split("\n"):
        block: dict[str, Any] = {"kind": "text"}
        want = line.strip()
        if want:
            for index in range(at, min(at + LOOKAHEAD, len(items))):
                if items[index]["first"] == want:
                    item = items[index]
                    block = {k: v for k, v in item.items() if k not in ("first", "text")}
                    at = index + 1
                    break
        block["text"] = line if len(line) <= LINE_CLIP else line[:LINE_CLIP] + "…"
        block["start"] = offset
        blocks.append(block)
        offset += len(line) + 1
    return blocks


def window(blocks: list[dict[str, Any]], at: int | None) -> dict[str, Any]:
    """At most `MAX_BLOCKS` blocks around the offset `at` (a match) in the stored text."""
    first = 0
    if at is not None:
        for index, block in enumerate(blocks):
            if block["start"] + len(block["text"]) >= at:
                first = max(0, index - MAX_BLOCKS // 4)
                break
        else:
            first = max(0, len(blocks) - MAX_BLOCKS)
    return {"blocks": blocks[first : first + MAX_BLOCKS], "first": first, "total": len(blocks)}


class Cache:
    """The structure of the last few documents read, so switching between matches does not read the
    file again."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, str, int, int], list[Item]] = {}
        self._lock = threading.Lock()

    def get(self, path: str, kind: str) -> list[Item]:
        try:
            real = os.path.realpath(path)
            stat = os.stat(real)
        except OSError:
            return []
        key = (kind, real, stat.st_mtime_ns, stat.st_size)
        with self._lock:
            found = self._files.pop(key, None)
            if found is not None:
                self._files[key] = found
                return found
        items = structure(real, kind)
        with self._lock:
            self._files[key] = items
            while len(self._files) > KEEP_FILES:
                del self._files[next(iter(self._files))]
        return items
