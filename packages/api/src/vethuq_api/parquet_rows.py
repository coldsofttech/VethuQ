"""A Parquet file read from disk as rows, for the table preview: the same rows VethuQ indexed.

The Parquet add-on indexes a table as text: a first line with the column names, then a line per
row that has something in it (the row's non-empty values, joined by " | "). The preview numbers
its rows the same way, so a search match's `line` is a row number here: row 1 is the column names
and row N the Nth row with something in it. The rows are made into the table code CSV files use
(`CsvFile`), which sorts, filters and maps a match to its cell.

PyArrow comes with the Parquet add-on, so it is imported when a file is read; without it the
preview says so. The text of a cell is made as the add-on makes it (`vethuq_addon_parquet.reader`),
because a match is found in that text.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from vethuq_api.csv_rows import CsvFile

# The add-on indexes up to this much text; the preview shows the same rows, so a match in the
# rows it indexed can always be shown.
MAX_TEXT_CHARS = 64 * 1024 * 1024
BATCH_ROWS = 8192
SEPARATOR = " | "


def _json_default(value: object) -> str:
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray):
        return f"<binary {len(value)} bytes>"
    return str(value)


def cell(value: object) -> str:
    """`value` as the text of one cell, empty for a null (as the Parquet add-on writes it)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, bytes | bytearray):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal | int | float):
        return str(value)
    if isinstance(value, list | tuple | dict):
        try:
            text = json.dumps(value, default=_json_default, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
        return " ".join(text.split())
    return " ".join(str(value).split())


def _values(column: Any, pa: Any) -> list[object]:
    try:
        return column.to_pylist()
    except (ValueError, OverflowError, pa.ArrowException):
        pass
    try:
        return column.cast(pa.string()).to_pylist()
    except (ValueError, OverflowError, pa.ArrowException):
        return [None] * len(column)


def read(path: str) -> CsvFile:
    """The table in `path` as rows: the column names first, then each row with something in it,
    up to the amount of text the add-on indexes. Raises `ValueError` (with a reason a person can
    read) if it cannot be shown."""
    try:
        import pyarrow as pa  # noqa: PLC0415 - installed with the Parquet add-on
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ImportError as error:
        raise ValueError(
            "Install the Parquet add-on (it brings PyArrow) to show this table."
        ) from error
    try:
        with open(path, "rb") as handle:
            file = pq.ParquetFile(handle)
            names = [str(name) for name in file.schema_arrow.names]
            rows: list[list[str]] = [names]
            # The add-on's count of text, line by line (a line and its newline), so the rows cut
            # off here are the rows it cut off.
            used = len(SEPARATOR.join(name for name in names if name.strip())) + 1
            for batch in file.iter_batches(batch_size=BATCH_ROWS):
                columns = [_values(column, pa) for column in batch.columns]
                for values in zip(*columns, strict=True):
                    texts = [cell(value) for value in values]
                    shown = [text for text in texts if text]
                    if not shown:
                        continue
                    used += len(SEPARATOR.join(shown)) + 1
                    if used > MAX_TEXT_CHARS:
                        return _table(rows, names, truncated=True)
                    rows.append(texts)
    except FileNotFoundError:
        raise
    except (pa.ArrowException, OSError) as error:
        raise ValueError("This is not a readable Parquet file (damaged or encrypted).") from error
    return _table(rows, names)


def _table(rows: list[list[str]], names: list[str], truncated: bool = False) -> CsvFile:
    return CsvFile(
        rows=rows,
        delimiter="",
        encoding="parquet",
        columns=len(names),
        header_detected=True,  # the column names are always the header
        truncated=truncated,
    )
