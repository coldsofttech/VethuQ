"""The CSV rows of the table preview: numbered like the index, sorted, filtered, and mapped back."""

from __future__ import annotations

import pytest

from vethuq_api import csv_rows
from vethuq_api.csv_rows import CsvCache, CsvFile


def write(tmp_path, text, name="t.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return str(path)


class TestReading:
    def test_empty_rows_are_left_out_like_the_index_does(self, tmp_path):
        file = CsvFile.read(write(tmp_path, "a,b\n\n , \nc,d\n"))
        assert file.rows == [["a", "b"], ["c", "d"]]  # row numbers 1 and 2, as `line` counts

    def test_a_quoted_newline_stays_in_its_cell(self, tmp_path):
        file = CsvFile.read(write(tmp_path, 'a,b\n"x\ny",2\n'))
        assert file.rows[1] == ["x\ny", "2"]

    @pytest.mark.parametrize(("text", "delimiter"), [("a;b\n1;2\n", ";"), ("a\tb\n1\t2\n", "\t")])
    def test_the_delimiter_is_sniffed(self, tmp_path, text, delimiter):
        file = CsvFile.read(write(tmp_path, text))
        assert file.delimiter == delimiter and file.rows[1] == ["1", "2"]

    def test_a_given_delimiter_is_used_and_nothing_is_sniffed(self, tmp_path):
        path = write(tmp_path, "a,b\tc\n1,2\t3\n", "t.tsv")
        file = CsvFile.read(path, "\t")
        assert file.delimiter == "\t" and file.rows == [["a,b", "c"], ["1,2", "3"]]
        assert CsvFile.read(path).delimiter == ","  # sniffed, as for any CSV

    def test_the_cache_keeps_a_file_read_one_way_apart_from_the_other(self, tmp_path):
        path = write(tmp_path, "a,b\tc\n", "t.tsv")
        cache = CsvCache()
        assert cache.get(path, "\t") is cache.get(path, "\t")
        assert cache.get(path, "\t") is not cache.get(path)

    def test_the_encoding_is_read(self, tmp_path):
        file = CsvFile.read(write(tmp_path, "name\ncafé\n", encoding="utf-16"))
        assert file.encoding == "utf-16" and file.rows[1] == ["café"]
        latin = CsvFile.read(write(tmp_path, "name\ncafé\n", "l.csv", encoding="cp1252"))
        assert latin.rows[1][0].startswith("caf")

    def test_a_file_that_is_too_big_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(csv_rows, "MAX_BYTES", 10)
        with pytest.raises(ValueError, match="too large"):
            CsvFile.read(write(tmp_path, "a,b\n1,2\n3,4\n"))

    def test_the_cache_rereads_a_changed_file(self, tmp_path):
        path = write(tmp_path, "a\n1\n")
        cache = CsvCache()
        assert cache.get(path) is cache.get(path)
        before = cache.get(path)
        (tmp_path / "t.csv").write_text("a\n1\n2\n", encoding="utf-8")
        assert cache.get(path) is not before and len(cache.get(path).rows) == 3


class TestHeader:
    def test_distinct_words_above_more_rows_are_a_header(self, tmp_path):
        assert CsvFile.read(write(tmp_path, "name,crop\nfarm,wheat\n")).header_detected

    @pytest.mark.parametrize(
        "text",
        ["1,2\n3,4\n", "a,a\nb,c\n", "a,\nb,c\n", "only,one\n"],
        ids=["numbers", "repeats", "empty cell", "one row"],
    )
    def test_anything_else_is_not(self, tmp_path, text):
        assert not CsvFile.read(write(tmp_path, text)).header_detected


class TestViews:
    @pytest.fixture
    def file(self, tmp_path):
        text = "name,qty\nbeta,10\nalpha,9\ngamma,\ndelta,100\nAlpha two,1\n"
        return CsvFile.read(write(tmp_path, text))

    def names(self, file, ids):
        return [file.rows[i][0] for i in ids]

    def test_the_header_is_not_a_row_of_the_view(self, file):
        assert len(file.view(True, None, False, "", None)) == 5
        assert len(file.view(False, None, False, "", None)) == 6

    def test_numbers_sort_by_value_and_empty_cells_stay_last(self, file):
        up = self.names(file, file.view(True, 1, False, "", None))
        assert up == ["Alpha two", "alpha", "beta", "delta", "gamma"]
        down = self.names(file, file.view(True, 1, True, "", None))
        assert down == ["delta", "beta", "alpha", "Alpha two", "gamma"]

    def test_text_sorts_without_regard_to_case(self, file):
        assert self.names(file, file.view(True, 0, False, "", None)) == [
            "alpha",
            "Alpha two",
            "beta",
            "delta",
            "gamma",
        ]

    def test_filtering_in_every_column_or_one(self, file):
        assert self.names(file, file.view(True, None, False, "ALPHA", None)) == [
            "alpha",
            "Alpha two",
        ]
        assert self.names(file, file.view(True, None, False, "1", None)) == [
            "beta",
            "delta",
            "Alpha two",
        ]
        assert self.names(file, file.view(True, None, False, "1", 0)) == []
        assert self.names(file, file.view(True, None, False, "1", 1)) == [
            "beta",
            "delta",
            "Alpha two",
        ]

    def test_a_view_is_kept_for_the_next_window(self, file):
        first = file.view(True, 1, False, "", None)
        assert file.view(True, 1, False, "", None) is first


class TestTargetCell:
    @pytest.fixture
    def file(self, tmp_path):
        return CsvFile.read(write(tmp_path, "id,name,note\n1,Ada,\n2,  Grace   Hopper ,ok\n"))

    def test_a_column_in_the_indexed_line_is_the_cell_that_holds_it(self, file):
        # Row 3 is indexed as "2 | Grace Hopper | ok" (cells collapsed, empty ones dropped).
        row = file.rows[2]
        assert file.cell_at(row, 1) == 0  # "2"
        assert file.cell_at(row, 5) == 1  # the G of "Grace Hopper"
        assert file.cell_at(row, 18) == 1  # the r that ends "Hopper"
        assert file.cell_at(row, 22) == 2  # "ok"
        assert file.cell_at(row, 99) is None

    def test_empty_cells_do_not_take_a_place_in_the_line(self, file):
        # "1 | Ada": the empty third cell is not in it, so it is never the answer.
        assert [file.cell_at(file.rows[1], n) for n in (1, 5, 7)] == [0, 1, 1]
