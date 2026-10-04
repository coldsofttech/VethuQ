from datetime import datetime

import pytest
from vethuq_core.formatting import Formatting


class TestSize:
    @pytest.mark.parametrize(
        ("num_bytes", "expected"),
        [
            (None, "-"),
            (0, "0 B"),
            (512, "512 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (5 * 1024 * 1024, "5.0 MB"),
            (3 * 1024**3, "3.0 GB"),
            (2048 * 1024**3, "2048.0 GB"),
        ],
    )
    def test_size(self, num_bytes, expected):
        assert Formatting.size(num_bytes) == expected


class TestSeconds:
    def test_missing_value_is_a_dash(self):
        assert Formatting.seconds(None) == "-"

    def test_one_decimal(self):
        assert Formatting.seconds(2.55) in ("2.5s", "2.6s")
        assert Formatting.seconds(0) == "0.0s"


class TestDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"), [(0, "0s"), (45.9, "45s"), (60, "1m 0s"), (185, "3m 5s")]
    )
    def test_duration(self, seconds, expected):
        assert Formatting.duration(seconds) == expected


class TestTimestamp:
    @pytest.mark.parametrize("value", [None, ""])
    def test_missing_value_is_a_dash(self, value):
        assert Formatting.timestamp(value) == "-"

    def test_renders_local_time(self):
        value = "2026-10-04T12:30:05+00:00"
        expected = datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")

        assert Formatting.timestamp(value) == expected

    def test_short_timestamp_drops_leading_zero_and_seconds(self):
        assert Formatting.short_timestamp("2026-10-04T09:05:30") == "4 Oct 2026 09:05"

    def test_short_timestamp_returns_non_timestamps_unchanged(self):
        assert Formatting.short_timestamp("not a date") == "not a date"
