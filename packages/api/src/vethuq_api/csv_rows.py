"""A CSV or TSV file read from disk as rows, for the table preview: the same rows VethuQ indexed.

The index keeps one line per non-empty row (its non-empty cells, spaces collapsed, joined by
" | "), so the rows here are numbered the same way: `row_number` N is the Nth row with something in
it, which is the `line` a search match reports. Parsing, sorting and filtering happen here, so the
browser is only ever sent the rows it shows.
"""

from __future__ import annotations

import codecs
import csv
import io
import os
import threading
from dataclasses import dataclass, field
from typing import Any

MAX_BYTES = 64 * 1024 * 1024
CELL_CLIP = 2000
KEEP_FILES = 2
KEEP_VIEWS = 4
DELIMITERS = ",;\t|"
SNIFF_CHARS = 64 * 1024
FIELD_LIMIT = 16 * 1024 * 1024
SEPARATOR = " | "

# Longest first, so a UTF-32 LE byte-order mark isn't taken for UTF-16 LE (as the CSV add-on does).
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode(data: bytes) -> tuple[str, str]:
    """The text in `data` and the encoding it was read as (a byte-order mark, clean UTF-8, then
    charset detection when it is installed, then Windows-1252)."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding), encoding
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes  # noqa: PLC0415 - optional

        match = from_bytes(data).best()
        if match is not None:
            return str(match), match.encoding
    except ImportError:
        pass
    if b"\x00" in data:
        raise ValueError("it contains binary data")
    return data.decode("cp1252", errors="replace"), "cp1252"


def _dialect(text: str) -> Any:
    sample = text[:SNIFF_CHARS]
    if len(text) > len(sample) and "\n" in sample:
        sample = sample[: sample.rindex("\n")]
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS)
    except csv.Error:
        return csv.excel


def _collapse(cell: str) -> str:
    return " ".join(cell.split())


def _number(cell: str) -> float | None:
    try:
        return float(cell.replace(",", "")) if cell.strip() else None
    except ValueError:
        return None


def _sort_key(cell: str) -> tuple[int, float, str]:
    """Numbers by value, then text without regard to case, then empty cells last."""
    text = cell.strip()
    if not text:
        return (2, 0.0, "")
    value = _number(text)
    if value is not None:
        return (0, value, "")
    return (1, 0.0, text.casefold())


@dataclass
class CsvFile:
    rows: list[list[str]]  # the non-empty rows, cells as they are in the file
    delimiter: str
    encoding: str
    columns: int
    header_detected: bool
    truncated: bool = False  # a Parquet table cut at the indexing limit
    views: dict[tuple, list[int]] = field(default_factory=dict)

    @classmethod
    def read(cls, path: str, delimiter: str | None = None) -> CsvFile:
        """The file's rows. The delimiter is sniffed, unless `delimiter` says what it is (a TSV
        file's is always a tab)."""
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            raise ValueError(
                f"This file is {size // (1024 * 1024)} MB, too large to preview "
                f"(the limit is {MAX_BYTES // (1024 * 1024)} MB). Open it instead."
            )
        with open(path, "rb") as handle:
            text, encoding = decode(handle.read())
        csv.field_size_limit(max(csv.field_size_limit(), FIELD_LIMIT))
        dialect = _dialect(text) if delimiter is None else csv.excel
        delimiter = dialect.delimiter if delimiter is None else delimiter
        rows: list[list[str]] = []
        try:
            for row in csv.reader(io.StringIO(text, newline=""), dialect, delimiter=delimiter):
                if any(_collapse(cell) for cell in row):
                    rows.append(row)
        except csv.Error as error:
            raise ValueError(str(error)) from error
        columns = max((len(row) for row in rows), default=0)
        return cls(rows, delimiter, encoding, columns, cls._header_looks_like(rows))

    @staticmethod
    def _header_looks_like(rows: list[list[str]]) -> bool:
        """A first row of distinct, non-empty words (no numbers) above at least one more row."""
        if len(rows) < 2:
            return False
        first = [_collapse(cell) for cell in rows[0]]
        return (
            all(first)
            and len(set(first)) == len(first)
            and all(_number(cell) is None for cell in first)
        )

    # ----- the rows of a view -----------------------------------------------------------------

    def view(
        self, header: bool, sort: int | None, descending: bool, needle: str, column: int | None
    ) -> list[int]:
        """The indexes (into `rows`) of the rows to show, filtered then sorted."""
        key = (header, sort, descending, needle.casefold(), column)
        kept = self.views.get(key)
        if kept is not None:
            return kept
        ids = range(1 if header else 0, len(self.rows))
        if needle:
            wanted = needle.casefold()
            if column is None:
                ids = [i for i in ids if any(wanted in cell.casefold() for cell in self.rows[i])]
            else:
                ids = [
                    i
                    for i in ids
                    if column < len(self.rows[i]) and wanted in self.rows[i][column].casefold()
                ]
        ids = list(ids)
        if sort is not None:
            ids.sort(
                key=lambda i: _sort_key(self.rows[i][sort] if sort < len(self.rows[i]) else ""),
                reverse=descending,
            )
            if descending:
                # Empty cells stay last in either direction.
                ids.sort(
                    key=lambda i: (
                        not ((self.rows[i][sort] if sort < len(self.rows[i]) else "").strip())
                    )
                )
        if len(self.views) >= KEEP_VIEWS:
            self.views.pop(next(iter(self.views)))
        self.views[key] = ids
        return ids

    def cell_at(self, row: list[str], offset: int) -> int | None:
        """The cell of `row` that holds the character at `offset` (from 1) of its indexed line."""
        position = 1
        for index, cell in enumerate(row):
            text = _collapse(cell)
            if not text:
                continue
            if offset < position + len(text):
                return index
            position += len(text) + len(SEPARATOR)
            if offset < position:
                return index
        return None

    def widths(self, ids: list[int], sample: int = 200) -> list[int]:
        """A width in characters for each column, from the longest cell among the first rows."""
        out = [4] * self.columns
        for i in ids[:sample]:
            for c, cell in enumerate(self.rows[i]):
                out[c] = max(out[c], min(len(cell), 40))
        if self.rows:
            for c, cell in enumerate(self.rows[0]):
                out[c] = max(out[c], min(len(cell), 40))
        return out


def clip(cell: str) -> str:
    return cell if len(cell) <= CELL_CLIP else cell[:CELL_CLIP] + "…"


class CsvCache:
    """The last few parsed files, so scrolling does not read the file again."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, int, int, str | None], CsvFile] = {}
        self._lock = threading.Lock()

    def get(self, path: str, delimiter: str | None = None, parquet: bool = False) -> CsvFile:
        """The parsed file: a Parquet table if `parquet`, else CSV text read with `delimiter` (or
        with the delimiter sniffed when it is None)."""
        real = os.path.realpath(path)
        stat = os.stat(real)
        key = (real, stat.st_mtime_ns, stat.st_size, "parquet" if parquet else delimiter)
        with self._lock:
            found = self._files.pop(key, None)
            if found is not None:
                self._files[key] = found  # most recently used last
                return found
        if parquet:
            from vethuq_api import parquet_rows  # noqa: PLC0415 - it builds a `CsvFile`

            parsed = parquet_rows.read(real)
        else:
            parsed = CsvFile.read(real, delimiter)
        with self._lock:
            self._files[key] = parsed
            while len(self._files) > KEEP_FILES:
                del self._files[next(iter(self._files))]
        return parsed
