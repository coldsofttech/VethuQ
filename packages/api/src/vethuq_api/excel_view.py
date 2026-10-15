"""A spreadsheet (Excel, OpenDocument) made into sheets and cells for the Excel preview.

The preview shows a workbook the way a spreadsheet program would (sheet tabs, a grid with column
letters and row numbers), but its match has to be found in the text the index kept: for each sheet
its name, then one line a row with the cells that have something in them joined by a tab. So the
cells are read from the file with their places, laid over that stored text line by line, and each
carries its offset in it. A line the file has no row for (a cell comment, a text box) is kept
apart as a note, and a file that cannot be read for its cells is shown as the stored rows alone.
The cells are read the way the XLSX, XLSM, XLSB, XLS, ODS and OTS add-ons read them, so the lines
are the same. Nothing is run, and a macro is never read.
"""

from __future__ import annotations

import os
import re
import threading
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from xml.etree.ElementTree import Element

MAX_PART_BYTES = 128 * 1024 * 1024
MAX_CELLS = 2_000_000
MAX_DEPTH = 200
MAX_REPEAT = 50
MAX_ROWS = 500
MAX_COLUMNS = 200
MAX_NOTES = 500
CELL_CLIP = 2_000
LOOKAHEAD = 8
KEEP_FILES = 2

Cell = tuple[int, str, bool]  # column (from 0), text, is a number
Sheet = dict[str, Any]  # {"name", "rows": [(row number from 1, [Cell])]}


def _xml_parser():
    try:
        from defusedxml import ElementTree as safe_xml  # noqa: PLC0415 - only for these files
    except ImportError as error:  # pragma: no cover - the add-ons need defusedxml
        raise ValueError(
            "defusedxml is not installed, so a workbook cannot be shown here."
        ) from error
    return safe_xml


# ----- how a cell's value becomes text (as the add-ons do it) ----------------------------------

_BUILTIN_DATES = frozenset({*range(14, 23), *range(27, 37), *range(45, 48)}) | frozenset(
    range(50, 59)
)
_QUOTED = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.')
_DATE_TOKEN = re.compile(r"[dmyhs]", re.IGNORECASE)


def _is_date(format_id: int, code: str | None) -> bool:
    if code is None:
        return format_id in _BUILTIN_DATES
    return bool(_DATE_TOKEN.search(_QUOTED.sub("", code)))


def _number(value: float | str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number or number in (float("inf"), float("-inf")):
        return str(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.15g}"


def _date(serial: float | str, *, date1904: bool) -> str:
    try:
        value = float(serial)
        if value < 0:
            raise ValueError
        epoch = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30 if value >= 61 else 31)
        moment = epoch + timedelta(seconds=round(value * 86400))
    except (ValueError, OverflowError):
        return _number(serial)
    if value < 1:
        return moment.strftime("%H:%M:%S")
    if moment.hour == moment.minute == moment.second == 0:
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m-%d %H:%M:%S")


# ----- Excel (.xlsx, .xlsm) ---------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _open(package: zipfile.ZipFile, name: str):
    if package.getinfo(name).file_size > MAX_PART_BYTES:
        raise ValueError(f"{name} is too large to read")
    return package.open(name)


def _item_text(element: Element) -> str:
    pieces: list[str] = []
    for child in element:
        if _local(child.tag) == "t":
            pieces.append(child.text or "")
        elif _local(child.tag) == "r":
            pieces.extend((sub.text or "") for sub in child if _local(sub.tag) == "t")
    return "".join(pieces)


def _column(reference: str) -> int | None:
    letters = re.match(r"[A-Za-z]+", reference or "")
    if not letters:
        return None
    number = 0
    for char in letters.group().upper():
        number = number * 26 + ord(char) - 64
    return number - 1


def _xlsx_cell(cell: Element, shared, date_styles, date1904) -> tuple[str, bool]:
    kind = cell.get("t", "n")
    raw = ""
    inline = ""
    for child in cell:
        if _local(child.tag) == "v":
            raw = child.text or ""
        elif _local(child.tag) == "is":
            inline = _item_text(child)
    if kind == "inlineStr":
        return inline.strip(), False
    if not raw:
        return "", False
    if kind == "s":
        try:
            return shared[int(raw)].strip(), False
        except (ValueError, IndexError):
            return "", False
    if kind == "b":
        return ("TRUE" if raw.strip() == "1" else "FALSE"), False
    if kind == "e":
        return "", False
    if kind in ("str", "d"):
        return raw.strip(), False
    if int(cell.get("s", "0") or 0) in date_styles:
        return _date(raw, date1904=date1904), False
    return _number(raw), True


def _xlsx(path: str) -> list[Sheet]:
    safe_xml = _xml_parser()
    with zipfile.ZipFile(path) as package:
        names = set(package.namelist())
        if "xl/workbook.xml" not in names:
            return []
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            with _open(package, "xl/sharedStrings.xml") as handle:
                for _, element in safe_xml.iterparse(handle):
                    if _local(element.tag) == "si":
                        shared.append(_item_text(element))
                        element.clear()
        date_styles: set[int] = set()
        if "xl/styles.xml" in names:
            with _open(package, "xl/styles.xml") as handle:
                root = safe_xml.parse(handle).getroot()
            codes: dict[int, str] = {}
            for section in root:
                if _local(section.tag) == "numFmts":
                    for fmt in section:
                        declared = fmt.get("numFmtId", "")
                        if declared.isdigit():
                            codes[int(declared)] = fmt.get("formatCode", "")
                elif _local(section.tag) == "cellXfs":
                    for index, xf in enumerate(section):
                        format_id = int(xf.get("numFmtId", "0") or 0)
                        if _is_date(format_id, codes.get(format_id)):
                            date_styles.add(index)
        with _open(package, "xl/workbook.xml") as handle:
            workbook = safe_xml.parse(handle).getroot()
        targets: dict[str, str] = {}
        rels = "xl/_rels/workbook.xml.rels"
        if rels in names:
            with _open(package, rels) as handle:
                for rel in safe_xml.parse(handle).getroot():
                    target = rel.get("Target", "")
                    targets[rel.get("Id", "")] = (
                        target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                    )
        date1904 = False
        listed: list[tuple[str, str]] = []
        for section in workbook:
            if _local(section.tag) == "workbookPr":
                date1904 = section.get("date1904", "0").lower() in ("1", "true")
            elif _local(section.tag) == "sheets":
                for sheet in section:
                    rel_id = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), "")
                    part = targets.get(rel_id)
                    if part in names:
                        listed.append((sheet.get("name", ""), part))
        if not listed:
            parts = sorted(
                (n for n in names if re.match(r"^xl/worksheets/[^/]+\.xml$", n)),
                key=lambda n: int(re.sub(r"\D", "", n) or 0),
            )
            listed = [(f"Sheet{i}", part) for i, part in enumerate(parts, start=1)]
        sheets: list[Sheet] = []
        budget = [MAX_CELLS]
        for name, part in listed:
            rows = list(_xlsx_rows(package, part, shared, date_styles, date1904, budget))
            sheets.append({"name": name, "rows": rows})
            if budget[0] <= 0:
                break
        return sheets


def _xlsx_rows(package, part, shared, date_styles, date1904, budget) -> Iterator[tuple[int, list]]:
    safe_xml = _xml_parser()
    cells: list[Cell] = []
    number = 0
    column = 0
    with _open(package, part) as handle:
        for _, element in safe_xml.iterparse(handle):
            tag = _local(element.tag)
            if tag == "c":
                found = _column(element.get("r", ""))
                position = column if found is None else found
                column = position + 1
                text, is_number = _xlsx_cell(element, shared, date_styles, date1904)
                if text:
                    cells.append((position, text, is_number))
            elif tag == "row":
                declared = element.get("r", "")
                number = int(declared) if declared.isdigit() else number + 1
                if cells:
                    budget[0] -= len(cells)
                    yield number, cells
                cells = []
                column = 0
                element.clear()
                if budget[0] <= 0:
                    return
    if cells:
        yield number + 1, cells


# ----- Excel binary (.xlsb) and legacy Excel (.xls) ---------------------------------------------


def _xlsb(path: str) -> list[Sheet]:
    from pyxlsb import open_workbook  # noqa: PLC0415 - only for these files

    book = open_workbook(path)
    try:
        sheets: list[Sheet] = []
        budget = MAX_CELLS
        for index, name in enumerate(book.sheets, start=1):
            rows: list[tuple[int, list[Cell]]] = []
            with book.get_sheet(index) as sheet:
                for row in sheet.rows(sparse=True):
                    cells: list[Cell] = []
                    number = 0
                    for cell in row:
                        value = cell.v
                        if value is None:
                            continue
                        number = cell.r + 1
                        if isinstance(value, bool):
                            text, num = ("TRUE" if value else "FALSE"), False
                        elif isinstance(value, float | int):
                            text, num = _number(value), True
                        else:
                            text, num = str(value).strip(), False
                        if text:
                            cells.append((cell.c, text, num))
                    if cells:
                        budget -= len(cells)
                        rows.append((number, cells))
                    if budget <= 0:
                        break
            sheets.append({"name": name, "rows": rows})
            if budget <= 0:
                break
        return sheets
    finally:
        book.close()


def _xls(path: str) -> list[Sheet]:
    import io  # noqa: PLC0415

    import xlrd  # noqa: PLC0415 - only for these files

    book = xlrd.open_workbook(path, on_demand=True, logfile=io.StringIO())
    try:
        sheets: list[Sheet] = []
        budget = MAX_CELLS
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)
            rows: list[tuple[int, list[Cell]]] = []
            for number in range(sheet.nrows):
                cells: list[Cell] = []
                for column, cell in enumerate(sheet.row(number)):
                    num = False
                    if cell.ctype == xlrd.XL_CELL_TEXT:
                        text = str(cell.value).strip()
                    elif cell.ctype == xlrd.XL_CELL_NUMBER:
                        text, num = _number(cell.value), True
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        text = _date(cell.value, date1904=book.datemode == 1)
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        text = "TRUE" if cell.value else "FALSE"
                    else:
                        text = ""
                    if text:
                        cells.append((column, text, num))
                if cells:
                    budget -= len(cells)
                    rows.append((number + 1, cells))
                if budget <= 0:
                    break
            book.unload_sheet(index)
            sheets.append({"name": sheet.name, "rows": rows})
            if budget <= 0:
                break
        return sheets
    finally:
        book.release_resources()


# ----- OpenDocument spreadsheets (.ods, .ots) ---------------------------------------------------

_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
_NUMBER_TYPES = ("float", "percentage", "currency")


def _inline(element: Element, depth: int = 0) -> str:
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
            out.append(_inline(child, depth + 1))
        out.append(child.tail or "")
    return "".join(out)[:1_000_000]


def _blocks(element: Element, depth: int = 0) -> list[str]:
    if depth > MAX_DEPTH:
        return []
    lines: list[str] = []
    for child in element:
        tag = child.tag
        if tag in (_TEXT + "p", _TEXT + "h"):
            line = _inline(child).strip()
            if line:
                lines.append(line)
            for note in child.iter(_TEXT + "note"):
                body = note.find(_TEXT + "note-body")
                if body is not None:
                    lines.extend(_blocks(body, depth + 1))
        elif tag == _TABLE + "table":
            lines.extend(_ods_lines(child))
        elif tag in (
            _OFFICE + "scripts",
            _OFFICE + "forms",
            _TEXT + "tracked-changes",
            _TEXT + "sequence-decls",
        ):
            continue
        else:
            lines.extend(_blocks(child, depth + 1))
    return lines


def _ods_cell_text(cell: Element) -> str:
    shown = " ".join(_blocks(cell)).strip()
    if shown:
        return shown
    value = cell.get(_OFFICE + "string-value") or cell.get(_OFFICE + "value")
    if value is None:
        value = cell.get(_OFFICE + "date-value") or cell.get(_OFFICE + "time-value")
    if value is None and cell.get(_OFFICE + "boolean-value") is not None:
        value = cell.get(_OFFICE + "boolean-value", "").upper()
    return (value or "").replace("T", " ", 1) if cell.get(_OFFICE + "date-value") else (value or "")


def _repeats(element: Element, name: str, cap: int = MAX_REPEAT) -> int:
    raw = element.get(_TABLE + name, "1")
    return min(int(raw), cap) if raw.isdigit() and int(raw) > 0 else 1


def _ods_row_elements(table: Element, depth: int = 0) -> list[Element]:
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
            found.extend(_ods_row_elements(child, depth + 1))
    return found


def _ods_lines(table: Element) -> list[str]:
    """What the add-on makes of a nested table: a line a row."""
    return ["\t".join(t for _, t, _ in cells) for _, cells in _ods_rows(table)]


def _ods_rows(table: Element) -> list[tuple[int, list[Cell]]]:
    rows: list[tuple[int, list[Cell]]] = []
    number = 0
    for row in _ods_row_elements(table):
        copies = _repeats(row, "number-rows-repeated")
        advance = _repeats(row, "number-rows-repeated", 10**9)
        cells: list[Cell] = []
        column = 0
        for cell in row:
            if cell.tag not in (_TABLE + "table-cell", _TABLE + "covered-table-cell"):
                continue
            width = _repeats(cell, "number-columns-repeated", 10**9)
            if cell.tag == _TABLE + "table-cell":
                shown = _ods_cell_text(cell)
                if shown:
                    is_number = cell.get(_OFFICE + "value-type") in _NUMBER_TYPES
                    for k in range(min(width, MAX_REPEAT)):
                        cells.append((column + k, shown, is_number))
            column += width
        if cells:
            for k in range(copies):
                rows.append((number + k + 1, cells))
        number += advance
    return rows


def _ods(path: str) -> list[Sheet]:
    safe_xml = _xml_parser()
    with zipfile.ZipFile(path) as package:
        if "content.xml" not in package.namelist():
            return []
        if package.getinfo("content.xml").file_size > 256 * 1024 * 1024:
            raise ValueError("content.xml is too large to read")
        root = safe_xml.fromstring(package.read("content.xml"))
    body = root.find(_OFFICE + "body")
    book = body.find(_OFFICE + "spreadsheet") if body is not None else None
    if book is None:
        return []
    sheets: list[Sheet] = []
    budget = MAX_CELLS
    for table in book.findall(_TABLE + "table"):
        rows = _ods_rows(table)
        budget -= sum(len(cells) for _, cells in rows)
        sheets.append({"name": table.get(_TABLE + "name", ""), "rows": rows})
        if budget <= 0:
            break
    return sheets


# ----- laying it out ----------------------------------------------------------------------------


def sheets_of(path: str, kind: str) -> list[Sheet]:
    """The sheets of the workbook at `path` with their cells and where each is; empty when the file
    gives none (or cannot be read for them)."""
    try:
        if kind in ("xlsx", "xlsm"):
            return _xlsx(path)
        if kind == "xlsb":
            return _xlsb(path)
        if kind == "xls":
            return _xls(path)
        if kind in ("ods", "ots"):
            return _ods(path)
    except Exception:  # noqa: BLE001 - the cells are a bonus: the stored rows are shown without them
        return []
    return []


def layout(text: str, sheets: list[Sheet]) -> dict[str, Any]:
    """The stored `text` laid over the cells of `sheets`: `{sheets: [{name, name_start, rows}],
    notes}`, each cell `[column, text, is_number, start]` with `start` its offset in `text`. A
    stored line that is a sheet's name or a row takes its place (within a few lines of the last
    one); any other is a note. With no sheets to lay it over, the stored lines are one sheet."""
    expected: list[tuple[str, int, int, str]] = []  # kind, sheet, row index, first
    for number, sheet in enumerate(sheets):
        if sheet["rows"]:
            expected.append(("name", number, -1, sheet["name"].strip()))
            for row_index, (_, cells) in enumerate(sheet["rows"]):
                expected.append(("row", number, row_index, "\t".join(c[1] for c in cells).strip()))
    laid = [
        {"name": s["name"], "name_start": None, "rows": [None] * len(s["rows"]), "numbers": []}
        for s in sheets
    ]
    notes: list[dict[str, Any]] = []
    loose: list[tuple[int, str]] = []
    offset = 0
    at = 0
    for line in text.split("\n"):
        want = line.strip()
        taken = None
        if want:
            for index in range(at, min(at + LOOKAHEAD, len(expected))):
                if expected[index][3] == want:
                    taken = expected[index]
                    at = index + 1
                    break
        if taken is None:
            loose.append((offset, line))
        elif taken[0] == "name":
            laid[taken[1]]["name_start"] = offset + (len(line) - len(line.lstrip()))
        else:
            _, cells = sheets[taken[1]]["rows"][taken[2]]
            position = offset + (len(line) - len(line.lstrip()))
            placed = []
            for column, cell_text, is_number in cells:
                placed.append([column, cell_text, is_number, position])
                position += len(cell_text) + 1
            laid[taken[1]]["rows"][taken[2]] = placed
        offset += len(line) + 1
    if not sheets:
        rows = []
        for start, line in loose:
            if not line.strip():
                continue
            position = start
            cells = []
            for column, cell_text in enumerate(line.split("\t")):
                cells.append([column, cell_text, False, position])
                position += len(cell_text) + 1
            rows.append(cells)
        one = {
            "name": "",
            "name_start": None,
            "rows": rows,
            "numbers": list(range(1, len(rows) + 1)),
        }
        one["bounds"] = _bounds(one)
        return {"sheets": [one], "notes": []}
    for number, sheet in enumerate(sheets):  # drop rows the stored text did not have
        numbers = [n for n, _ in sheet["rows"]]
        kept = [i for i, r in enumerate(laid[number]["rows"]) if r is not None]
        laid[number]["numbers"] = [numbers[i] for i in kept]
        laid[number]["rows"] = [laid[number]["rows"][i] for i in kept]
        laid[number]["bounds"] = _bounds(laid[number])
    for start, line in loose[:MAX_NOTES]:
        if line.strip():
            clip = line if len(line) <= CELL_CLIP else line[:CELL_CLIP] + "…"
            notes.append({"text": clip, "start": start})
    return {"sheets": laid, "notes": notes}


def _bounds(one: dict[str, Any]) -> tuple[int | None, int | None]:
    """Where a sheet's text begins and ends in the stored text (its name, then its rows)."""
    low = one["name_start"]
    if low is None and one["rows"]:
        low = one["rows"][0][0][3]
    high = low
    if one["rows"]:
        last = one["rows"][-1][-1]
        high = last[3] + len(last[1])
    return low, high


def _find(rows: list[list], at: int) -> int | None:
    """The index of the row holding offset `at` (or the first row after it)."""
    low, high = 0, len(rows)
    while low < high:
        middle = (low + high) // 2
        last = rows[middle][-1]
        if last[3] + len(last[1]) < at:
            low = middle + 1
        else:
            high = middle
    return low if low < len(rows) else None


def window(
    laid: dict[str, Any], at: int | None, sheet: int | None, first: int | None
) -> dict[str, Any]:
    """The answer for the preview: the sheets (name, rows, columns), and one sheet's cells from row
    `first`, at most `MAX_ROWS` rows and `MAX_COLUMNS` columns. With no sheet asked for, the sheet
    holding the match (offset `at`), else the first, and with no row asked for, around the match."""
    sheets = laid["sheets"]
    summary = []
    for one in sheets:
        width = max((r[-1][0] + 1 for r in one["rows"] if r), default=0)
        summary.append(
            {
                "name": one["name"],
                "name_start": one["name_start"],
                "rows": len(one["rows"]),
                "cols": width,
            }
        )
    chosen = sheet
    if chosen is None or not 0 <= chosen < len(sheets):
        chosen = 0
        if at is not None:
            for number, one in enumerate(sheets):
                low, high = one["bounds"]
                if low is not None and low <= at <= high:
                    chosen = number
                    break
    one = sheets[chosen] if sheets else {"rows": [], "numbers": []}
    total = len(one["rows"])
    if first is None:
        index = _find(one["rows"], at) if at is not None and total else None
        first = max(0, index - MAX_ROWS // 4) if index is not None else 0
    first = min(max(first, 0), max(total - 1, 0))
    shown = []
    for index in range(first, min(first + MAX_ROWS, total)):
        cells = [
            {"c": c, "t": t if len(t) <= CELL_CLIP else t[:CELL_CLIP] + "…", "n": n, "s": s}
            for c, t, n, s in one["rows"][index]
            if c < MAX_COLUMNS
        ]
        shown.append({"r": one["numbers"][index], "cells": cells})
    return {
        "sheets": summary,
        "sheet": chosen,
        "first": first,
        "rows": shown,
        "notes": laid["notes"],
        "limited_columns": bool(summary and summary[chosen]["cols"] > MAX_COLUMNS)
        if summary
        else False,
    }


class Cache:
    """The cells of the last few workbooks read (laid over the stored text), so moving about a
    workbook does not read the file again."""

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
        sheets = sheets_of(real, kind) if readable else []
        laid = layout(text, sheets)
        with self._lock:
            self._files[signature] = laid
            while len(self._files) > KEEP_FILES:
                del self._files[next(iter(self._files))]
        return laid
