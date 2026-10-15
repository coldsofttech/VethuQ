"""A presentation (PowerPoint, OpenDocument) made into slides for the PowerPoint preview.

The preview shows a deck slide by slide (each slide's title, its text, its tables, its speaker
notes), but its match has to be found in the text the index kept: the slides' text one paragraph a
line, then the notes, then comments. So each slide's paragraphs are read from the file, in the
order the presentation add-ons read them, and laid over that stored text line by line, each with its
offset. A stored line the file has no paragraph for (a comment, SmartArt text) is kept apart as a
note, and a file that cannot be read for its slides is shown as the stored lines in one slide.
Nothing is run, and a macro is never read.
"""

from __future__ import annotations

import os
import posixpath
import re
import struct
import threading
import zipfile
from typing import Any
from xml.etree.ElementTree import Element

from vethuq_api.excel_view import _inline, _ods_lines, _xml_parser

MAX_PART_BYTES = 128 * 1024 * 1024
MAX_DEPTH = 200
MAX_SLIDES = 40
MAX_NOTES = 500
OUTLINE_CLIP = 80
LINE_CLIP = 5_000
LOOKAHEAD = 12
KEEP_FILES = 2

Entry = dict[str, Any]  # {"slide": int | None, "kind", "level", "text"} in the stored text's order

_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
_PRESENTATION = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _natural(name: str) -> list[object]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _read(package: zipfile.ZipFile, name: str) -> bytes:
    if package.getinfo(name).file_size > MAX_PART_BYTES:
        raise ValueError(f"{name} is too large to read")
    return package.read(name)


# ----- PowerPoint (.pptx, .pptm, .ppsx) ---------------------------------------------------------

_SLIDE_PART = re.compile(r"^ppt/slides/slide\d+\.xml$")
_NOTES_PART = re.compile(r"^ppt/notesSlides/notesSlide\d+\.xml$")
_COMMENT_PART = re.compile(r"^ppt/comments/[^/]+\.xml$")
_DIAGRAM_PART = re.compile(r"^ppt/diagrams/data\d*\.xml$")
_TITLES = ("title", "ctrTitle")


def _relationships(package, part: str, names: set[str]) -> list[tuple[str, str, str]]:
    directory, _, name = part.rpartition("/")
    rels = f"{directory}/_rels/{name}.rels"
    if rels not in names:
        return []
    try:
        root = _xml_parser().fromstring(_read(package, rels))
    except Exception:  # noqa: BLE001 - a part we cannot read has no relationships
        return []
    found = []
    for rel in root:
        target = rel.get("Target")
        if not target or rel.get("TargetMode") == "External":
            continue
        resolved = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(directory, target))
        )
        found.append((rel.get("Id", ""), rel.get("Type", ""), resolved))
    return found


def _pptx_slides(package, names: set[str]) -> list[str]:
    ordered: list[str] = []
    try:
        targets = {i: part for i, _, part in _relationships(package, "ppt/presentation.xml", names)}
        root = _xml_parser().fromstring(_read(package, "ppt/presentation.xml"))
        for element in root.iter():
            if _local(element.tag) != "sldId":
                continue
            rel_id = next((v for k, v in element.attrib.items() if k.endswith("}id")), None)
            part = targets.get(rel_id or "")
            if part in names and _SLIDE_PART.match(part) and part not in ordered:
                ordered.append(part)
    except Exception:  # noqa: BLE001, S110 - the order is the add-on's, else by number
        pass
    rest = (n for n in names if _SLIDE_PART.match(n) and n not in ordered)
    return ordered + sorted(rest, key=_natural)


def _pptx_text(paragraph: Element) -> str:
    pieces: list[str] = []

    def walk(element: Element) -> None:
        for child in element:
            tag = _local(child.tag)
            if tag == "t":
                pieces.append(child.text or "")
            elif tag == "br":
                pieces.append("\n")
            elif tag == "fld" and (child.get("type") or "").startswith("slidenum"):
                continue
            elif tag in ("rPr", "pPr", "endParaRPr"):
                continue
            else:
                walk(child)

    walk(paragraph)
    return "".join(pieces)


def _pptx_paragraphs(root: Element, kind: str | None = None) -> list[tuple[str, int, str]]:
    """The paragraphs of a presentation part in order as `(kind, level, text)`: what the add-on
    reads, with what each is (title, body text, text) from the shape it is in."""
    found: list[tuple[str, int, str]] = []

    def walk(element: Element, shape: str, depth: int) -> None:
        tag = _local(element.tag)
        if tag == "Fallback" or depth > MAX_DEPTH:
            return
        if tag == "sp":
            placeholder = next((e for e in element.iter() if _local(e.tag) == "ph"), None)
            if placeholder is None:
                shape = "text"
            elif placeholder.get("type") in _TITLES:
                shape = "title"
            elif placeholder.get("type") == "subTitle":
                shape = "subtitle"
            elif placeholder.get("type") in (None, "body", "obj"):
                shape = "list"
            else:
                shape = "text"
        if tag == "p":
            text = _pptx_text(element)
            if text.strip():
                properties = next((c for c in element if _local(c.tag) == "pPr"), None)
                level = properties.get("lvl", "0") if properties is not None else "0"
                found.append((shape, int(level) if level.isdigit() else 0, text))
            return
        if tag == "tbl":
            for row in element:
                if _local(row.tag) != "tr":
                    continue
                cells = [
                    " ".join(" ".join(t for _, _, t in _pptx_paragraphs(cell)).split())
                    for cell in row
                    if _local(cell.tag) == "tc"
                ]
                if any(cells):
                    found.append(("row", 0, "\t".join(cells)))
            return
        for child in element:
            walk(child, shape, depth + 1)

    walk(root, kind or "text", 0)
    return found


def _pptx_notes(root: Element) -> list[str]:
    found: list[str] = []
    for shape in root.iter():
        if _local(shape.tag) != "sp":
            continue
        placeholder = next((e for e in shape.iter() if _local(e.tag) == "ph"), None)
        if placeholder is not None and placeholder.get("type") == "body":
            found.extend(t for _, _, t in _pptx_paragraphs(shape))
    return found


def _pptx_comments(root: Element) -> list[str]:
    found: list[str] = []
    for comment in root.iter():
        if _local(comment.tag) != "cm":
            continue
        for child in comment:
            if _local(child.tag) == "text":
                text = " ".join((child.text or "").split())
                if text:
                    found.append(text)
        found.extend(t for _, _, t in _pptx_paragraphs(comment))
    return found


def _pptx(path: str) -> tuple[list[Entry], int]:
    safe_xml = _xml_parser()
    with zipfile.ZipFile(path) as package:
        names = set(package.namelist())
        if "ppt/presentation.xml" not in names:
            return [], 0
        entries: list[Entry] = []
        notes: list[tuple[int | None, str]] = []
        slides = _pptx_slides(package, names)
        for number, slide in enumerate(slides):
            for kind, level, text in _pptx_paragraphs(safe_xml.fromstring(_read(package, slide))):
                entries.append({"slide": number, "kind": kind, "level": level, "text": text})
            for _, rel_type, target in _relationships(package, slide, names):
                if (
                    target in names
                    and rel_type.rsplit("/", 1)[-1] == "notesSlide"
                    and target not in [p for _, p in notes]
                ):
                    notes.append((number, target))
        listed = {p for _, p in notes}
        notes.extend(
            (None, n)
            for n in sorted(
                (n for n in names if _NOTES_PART.match(n) and n not in listed), key=_natural
            )
        )
        for owner, part in notes:
            for text in _pptx_notes(safe_xml.fromstring(_read(package, part))):
                entries.append({"slide": owner, "kind": "note", "level": 0, "text": text})
        for name in sorted(names, key=_natural):
            if _COMMENT_PART.match(name):
                root = safe_xml.fromstring(_read(package, name))
                for text in _pptx_comments(root):
                    entries.append({"slide": None, "kind": "comment", "level": 0, "text": text})
            elif _DIAGRAM_PART.match(name):
                root = safe_xml.fromstring(_read(package, name))
                for _, _, text in _pptx_paragraphs(root):
                    entries.append({"slide": None, "kind": "text", "level": 0, "text": text})
        return entries, len(slides)


# ----- legacy PowerPoint (.ppt, .pps) -----------------------------------------------------------

_TEXT_CHARS = 0x0FA0
_TEXT_BYTES = 0x0FA8
_TEXT_HEADER = 0x0F9F
_MAIN_MASTER = 0x03F8
_HANDOUT = 0x0FC9
_SLIDE_LIST = 0x0FF0
_SLIDE = 0x03EE
_NOTES = 0x03F0
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_TEXT_KINDS = {
    0: "title",
    6: "title",
    1: "list",
    5: "list",
    7: "list",
    8: "list",
    2: "note",
    3: "note",
}


def _ppt(path: str) -> tuple[list[Entry], int]:
    import olefile  # noqa: PLC0415 - only for these files

    if not olefile.isOleFile(path):
        return [], 0
    with olefile.OleFileIO(path) as ole:
        if not ole.exists("PowerPoint Document") or ole.exists("EncryptedSummary"):
            return [], 0
        stream = ole.openstream("PowerPoint Document").read()
    entries: list[Entry] = []
    state = {"slides": 0, "type": None}

    def add(raw: str, slide: int | None, in_notes: bool) -> None:
        text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n")
        text = _CONTROL.sub("", text).replace("\ufffd", "")
        lines = (line.strip(" \t") for line in text.split("\n"))
        text = "\n".join(line for line in lines if line)
        if not text:
            return
        kind = "note" if in_notes else _TEXT_KINDS.get(state["type"], "text")
        entries.append({"slide": slide, "kind": kind, "level": 0, "text": text})
        state["type"] = None

    def walk(start: int, end: int, depth: int, slide: int | None, in_notes: bool) -> None:
        position = start
        while position + 8 <= end:
            ver_inst, rec_type, length = struct.unpack_from("<HHI", stream, position)
            body = position + 8
            stop = body + length
            if stop > end:
                return
            if ver_inst & 0x0F == 0x0F:
                masters_text = rec_type == _SLIDE_LIST and ver_inst >> 4 == 1
                skipped = rec_type in (_MAIN_MASTER, _HANDOUT) or masters_text
                if not skipped and depth < 32:
                    here, notes = slide, in_notes
                    if rec_type == _SLIDE:
                        here, notes = state["slides"], False
                        state["slides"] += 1
                    elif rec_type == _NOTES:
                        here, notes = None, True
                    walk(body, stop, depth + 1, here, notes)
            elif rec_type == _TEXT_HEADER and length >= 4:
                (state["type"],) = struct.unpack_from("<I", stream, body)
            elif rec_type == _TEXT_CHARS:
                add(
                    stream[body : stop - length % 2].decode("utf-16-le", errors="replace"),
                    slide,
                    in_notes,
                )
            elif rec_type == _TEXT_BYTES:
                add(stream[body:stop].decode("cp1252", errors="replace"), slide, in_notes)
            position = stop

    walk(0, len(stream), 0, None, False)
    return entries, state["slides"]


# ----- OpenDocument presentations (.odp, .otp) --------------------------------------------------


def _odp_walk(element: Element, shape: str, listed: int, slide: int, entries: list[Entry], depth=0):
    """The paragraphs under a slide as the add-on reads them, with the kind of the shape each is
    in (its `presentation:class`)."""
    if depth > MAX_DEPTH:
        return
    for child in element:
        tag = child.tag
        if tag in (_TEXT + "p", _TEXT + "h"):
            line = _inline(child).strip()
            if line:
                if shape in ("title", "subtitle", "notes"):
                    kind = "note" if shape == "notes" else shape
                elif listed or shape == "outline":
                    kind = "list"
                else:
                    kind = "text"
                level = max(listed - 1, 0)
                entries.append({"slide": slide, "kind": kind, "level": level, "text": line})
            for note in child.iter(_TEXT + "note"):
                body = note.find(_TEXT + "note-body")
                if body is not None:
                    _odp_walk(body, "text", 0, slide, entries, depth + 1)
        elif tag == _TABLE + "table":
            for line in _ods_lines(child):
                entries.append({"slide": slide, "kind": "row", "level": 0, "text": line})
        elif tag in (
            _OFFICE + "scripts",
            _OFFICE + "forms",
            _TEXT + "tracked-changes",
            _TEXT + "sequence-decls",
        ):
            continue
        else:
            inner = shape
            if tag == _PRESENTATION + "notes":
                inner = "notes"
            elif child.get(_PRESENTATION + "class"):
                inner = child.get(_PRESENTATION + "class")
            _odp_walk(child, inner, listed + (tag == _TEXT + "list"), slide, entries, depth + 1)


def _odp(path: str) -> tuple[list[Entry], int]:
    safe_xml = _xml_parser()
    with zipfile.ZipFile(path) as package:
        if "content.xml" not in package.namelist():
            return [], 0
        root = safe_xml.fromstring(_read(package, "content.xml"))
    body = root.find(_OFFICE + "body")
    deck = body.find(_OFFICE + "presentation") if body is not None else None
    if deck is None:
        return [], 0
    entries: list[Entry] = []
    pages = deck.findall(_DRAW + "page")
    for number, page in enumerate(pages):
        _odp_walk(page, "text", 0, number, entries)
    return entries, len(pages)


# ----- laying it out ----------------------------------------------------------------------------


def entries_of(path: str, kind: str) -> tuple[list[Entry], int]:
    """The paragraphs of the presentation at `path` in the stored text's order and how many slides
    it has; nothing when the file gives none (or cannot be read for them)."""
    try:
        if kind in ("pptx", "pptm", "ppsx"):
            return _pptx(path)
        if kind in ("ppt", "pps"):
            return _ppt(path)
        if kind in ("odp", "otp"):
            return _odp(path)
    except Exception:  # noqa: BLE001 - the slides are a bonus: the stored lines are shown without them
        return [], 0
    return [], 0


def layout(text: str, entries: list[Entry], count: int) -> dict[str, Any]:
    """The stored `text` laid over `entries`: `{slides: [{items}], notes}`, each item
    `{kind, level, lines: [{text, start}]}`. A stored line that is a line of the next paragraph
    (within a few) takes its place; any other is a note (a comment, SmartArt text). With no entries
    to lay it over, the stored lines are the items of one slide."""
    expected: list[tuple[int, int, str]] = []  # entry, line, its text stripped
    for number, entry in enumerate(entries):
        for index, line in enumerate(entry["text"].split("\n")):
            if line.strip():
                expected.append((number, index, line.strip()))
    slides: list[dict[str, Any]] = [{"items": []} for _ in range(count)]
    placed: dict[int, dict[str, Any]] = {}
    notes: list[dict[str, Any]] = []
    loose: list[dict[str, Any]] = []
    offset = 0
    at = 0
    for line in text.split("\n"):
        want = line.strip()
        taken = None
        if want:
            for index in range(at, min(at + LOOKAHEAD, len(expected))):
                if expected[index][2] == want:
                    taken = expected[index]
                    at = index + 1
                    break
        shown = line if len(line) <= LINE_CLIP else line[:LINE_CLIP] + "…"
        if taken is None:
            if want:
                loose.append({"text": shown, "start": offset})
        else:
            entry = entries[taken[0]]
            item = placed.get(taken[0])
            if item is None:
                item = {"kind": entry["kind"], "level": entry["level"], "lines": []}
                placed[taken[0]] = item
                target = entry["slide"]
                if target is None:
                    item["loose"] = True
                else:
                    slides[target]["items"].append(item)
            item["lines"].append({"text": shown, "start": offset})
        offset += len(line) + 1
    for item in placed.values():
        if item.pop("loose", False):
            notes.extend({"text": line["text"], "start": line["start"]} for line in item["lines"])
    if not entries:
        slides = [{"items": [{"kind": "text", "level": 0, "lines": [line]} for line in loose]}]
        loose = []
    notes.extend(loose)
    notes.sort(key=lambda n: n["start"])
    return {"slides": slides, "notes": notes[:MAX_NOTES]}


def _bounds(slide: dict[str, Any]) -> tuple[int, int] | None:
    lines = [line for item in slide["items"] for line in item["lines"]]
    if not lines:
        return None
    return min(line["start"] for line in lines), max(
        line["start"] + len(line["text"]) for line in lines
    )


def window(laid: dict[str, Any], at: int | None, first: int | None) -> dict[str, Any]:
    """The answer for the preview: an outline of every slide (its number and title) and at most
    `MAX_SLIDES` slides from slide `first` (from 0; by default around the one with the match, offset
    `at` in the stored text)."""
    slides = laid["slides"]
    outline = []
    for number, slide in enumerate(slides):
        title = next(
            (i for i in slide["items"] if i["kind"] == "title"),
            slide["items"][0] if slide["items"] else None,
        )
        text = " ".join(title["lines"][0]["text"].split()) if title else ""
        outline.append({"n": number + 1, "title": text[:OUTLINE_CLIP]})
    if first is None:
        first = 0
        if at is not None:
            for number, slide in enumerate(slides):
                bounds = _bounds(slide)
                if bounds and bounds[0] <= at <= bounds[1]:
                    first = max(0, number - MAX_SLIDES // 4)
                    break
    first = min(max(first, 0), max(len(slides) - 1, 0))
    shown = [
        {"n": number + 1, "items": slides[number]["items"]}
        for number in range(first, min(first + MAX_SLIDES, len(slides)))
    ]
    return {
        "slides": shown,
        "first": first,
        "total": len(slides),
        "outline": outline,
        "notes": laid["notes"],
    }


class Cache:
    """The slides of the last few presentations read (laid over the stored text), so moving about a
    deck does not read the file again."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, str, int, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, path: str, kind: str, text: str, readable: bool = True) -> dict[str, Any]:
        try:
            real = os.path.realpath(path)
            stat = os.stat(real)
            signature = (kind, real, stat.st_mtime_ns, stat.st_size, hash(text))
        except OSError:
            real, readable, signature = path, False, (kind, path, 0, 0, hash(text))
        with self._lock:
            found = self._files.pop(signature, None)
            if found is not None:
                self._files[signature] = found
                return found
        entries, count = entries_of(real, kind) if readable else ([], 0)
        laid = layout(text, entries, count)
        with self._lock:
            self._files[signature] = laid
            while len(self._files) > KEEP_FILES:
                del self._files[next(iter(self._files))]
        return laid
