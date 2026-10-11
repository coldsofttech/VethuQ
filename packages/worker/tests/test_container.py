from __future__ import annotations

import struct

import pytest

from vethuq_worker import container
from vethuq_worker.errors import JobError

LIMIT = 10_000


class TestContainer:
    def test_roundtrip(self):
        entries = {"manifest.json": b"{}", "images/0001.png": b"\x89PNG", "images/0002.png": b""}
        assert container.unpack(container.pack(entries), max_bytes=LIMIT) == entries

    @pytest.mark.parametrize("name", ["../etc/passwd", "/abs.png", "images/x.png", "other.txt"])
    def test_unexpected_names_are_refused(self, name):
        with pytest.raises(JobError) as caught:
            container.unpack(container.pack({name: b"x"}), max_bytes=LIMIT)
        assert caught.value.code == "bad_payload"

    def test_total_size_is_capped(self):
        blob = container.pack({"images/0001.png": b"x" * 600, "images/0002.png": b"x" * 600})
        with pytest.raises(JobError):
            container.unpack(blob, max_bytes=1000)

    def test_declared_size_beyond_data_is_refused(self):
        blob = bytearray(container.pack({"manifest.json": b"{}"}))
        blob[-2 - 8 : -2] = struct.pack(">Q", 10**9)
        with pytest.raises(JobError):
            container.unpack(bytes(blob), max_bytes=LIMIT)

    @pytest.mark.parametrize("cut", [3, 9, 20])
    def test_cut_short_is_refused(self, cut):
        with pytest.raises(JobError):
            container.unpack(container.pack({"manifest.json": b"{}"})[:cut], max_bytes=LIMIT)

    def test_trailing_data_is_refused(self):
        with pytest.raises(JobError):
            container.unpack(container.pack({"manifest.json": b"{}"}) + b"x", max_bytes=LIMIT)

    def test_duplicate_names_are_refused(self):
        one = container.pack({"manifest.json": b"{}"})
        entry = one[8:]
        doubled = one[:4] + struct.pack(">I", 2) + entry + entry
        with pytest.raises(JobError):
            container.unpack(doubled, max_bytes=LIMIT)
