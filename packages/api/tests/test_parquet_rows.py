"""The Parquet rows of the table preview: the rows the Parquet add-on indexed, numbered alike."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from vethuq_api import parquet_rows  # noqa: E402
from vethuq_api.csv_rows import CsvCache  # noqa: E402


def write(tmp_path, table, name="t.parquet", **options):
    path = tmp_path / name
    pq.write_table(table if isinstance(table, pa.Table) else pa.table(table), path, **options)
    return str(path)


def table():
    return pa.table(
        {
            "name": ["Ada", None, "Cy", "Di"],
            "qty": [36, None, 7, None],
            "tags": pa.array([["math", "engines"], None, [], ["art"]], pa.list_(pa.string())),
            "day": [date(2026, 10, 14), None, None, date(2026, 1, 2)],
        }
    )


class TestReading:
    def test_the_column_names_are_row_one_and_the_header(self, tmp_path):
        file = parquet_rows.read(write(tmp_path, table()))
        assert file.rows[0] == ["name", "qty", "tags", "day"]
        assert file.header_detected is True and file.columns == 4
        assert file.encoding == "parquet" and file.delimiter == "" and file.truncated is False

    def test_a_row_with_nothing_in_it_is_left_out(self, tmp_path):
        file = parquet_rows.read(write(tmp_path, table()))
        # Row 3 of the file is all null (the empty list is a value, so it stays: row "Cy").
        assert [row[0] for row in file.rows[1:]] == ["Ada", "Cy", "Di"]

    def test_nulls_stay_in_place_so_a_cell_keeps_its_column(self, tmp_path):
        file = parquet_rows.read(write(tmp_path, table()))
        assert file.rows[1] == ["Ada", "36", '["math", "engines"]', "2026-10-14"]
        assert file.rows[2] == ["Cy", "7", "[]", ""]

    def test_many_row_groups_and_batches_keep_their_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(parquet_rows, "BATCH_ROWS", 7)
        path = write(tmp_path, {"n": list(range(100))}, row_group_size=30)
        file = parquet_rows.read(path)
        assert [row[0] for row in file.rows[1:]] == [str(n) for n in range(100)]

    def test_a_table_over_the_indexing_limit_is_cut_at_the_same_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(parquet_rows, "MAX_TEXT_CHARS", 40)
        file = parquet_rows.read(write(tmp_path, {"word": [f"word{n:03d}" for n in range(100)]}))
        assert file.truncated is True and 1 < len(file.rows) < 101

    def test_a_file_that_is_not_parquet_says_so(self, tmp_path):
        path = tmp_path / "bad.parquet"
        path.write_bytes(b"not a table")
        with pytest.raises(ValueError, match="not a readable Parquet file"):
            parquet_rows.read(str(path))

    def test_the_cache_keeps_a_table_apart_from_a_csv_reading_of_the_same_path(self, tmp_path):
        path = write(tmp_path, {"a": [1]})
        cache = CsvCache()
        assert cache.get(path, parquet=True) is cache.get(path, parquet=True)
        assert cache.get(path, parquet=True).encoding == "parquet"


class TestCells:
    @pytest.mark.parametrize(
        ("value", "text"),
        [
            (None, ""),
            (True, "true"),
            ("  two   words\n", "two words"),
            (b"\x00\x01", "<binary 2 bytes>"),
            (Decimal("12.50"), "12.50"),
            (date(2026, 10, 14), "2026-10-14"),
            (time(9, 30), "09:30:00"),
            (datetime(2026, 10, 14, 9, 30, tzinfo=UTC), "2026-10-14T09:30:00+00:00"),
            ({"name": "Ada", "city": "London"}, '{"name": "Ada", "city": "London"}'),
            ([("k", "v")], '[["k", "v"]]'),
        ],
    )
    def test_a_value_as_text(self, value, text):
        assert parquet_rows.cell(value) == text


class TestSameRowsAsTheIndex:
    """The preview shows the rows the add-on indexed: a match's line is a row here. This needs the
    add-on (licensed code that this checkout may not have), so it is skipped without it."""

    def test_every_line_of_the_indexed_text_is_a_row_of_the_preview(self, tmp_path):
        reader = pytest.importorskip("vethuq_addon_parquet.reader")
        big = pa.table(
            {
                "id": list(range(50)),
                "note": [None if n % 7 == 0 else f"first\n  second   {n}" for n in range(50)],
                "tags": pa.array([["a", "b"] if n % 5 else None for n in range(50)]),
                "at": pa.array([datetime(2026, 1, 1, tzinfo=UTC)] * 50, pa.timestamp("us", "UTC")),
                "blob": pa.array([b"\x00" * n for n in range(50)], pa.binary()),
                "price": pa.array([Decimal("1.10")] * 50, pa.decimal128(5, 2)),
            }
        )
        path = write(tmp_path, big, row_group_size=13)
        with open(path, "rb") as handle:
            text, _ = reader.ParquetReader.extract(handle)
        file = parquet_rows.read(path)
        indexed = text.split("\n")
        shown = [parquet_rows.SEPARATOR.join(cell for cell in row if cell) for row in file.rows]
        shown[0] = parquet_rows.SEPARATOR.join(file.rows[0])
        assert shown == indexed

    def test_a_match_is_mapped_to_its_cell(self, tmp_path):
        pytest.importorskip("vethuq_addon_parquet.reader")
        file = parquet_rows.read(write(tmp_path, table()))
        # Row 2 is "Ada | 36 | [...] | 2026-10-14": offset 7 is inside "36".
        assert file.cell_at(file.rows[1], 7) == 1
