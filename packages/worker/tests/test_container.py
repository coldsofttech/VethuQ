from __future__ import annotations

import struct

import pytest

from vethuq_worker.container import Container
from vethuq_worker.errors import JobError

LIMIT = 10_000


class TestContainer:
    def test_roundtrip(self):
        entries = {"manifest.json": b"{}", "images/0001.png": b"\x89PNG", "images/0002.png": b""}
        assert Container.unpack(Container.pack(entries), max_bytes=LIMIT) == entries

    @pytest.mark.parametrize("name", ["../etc/passwd", "/abs.png", "images/x.png", "other.txt"])
    def test_unexpected_names_are_refused(self, name):
        with pytest.raises(JobError) as caught:
            Container.unpack(Container.pack({name: b"x"}), max_bytes=LIMIT)
        assert caught.value.code == "bad_payload"

    def test_total_size_is_capped(self):
        blob = Container.pack({"images/0001.png": b"x" * 600, "images/0002.png": b"x" * 600})
        with pytest.raises(JobError):
            Container.unpack(blob, max_bytes=1000)

    def test_declared_size_beyond_data_is_refused(self):
        blob = bytearray(Container.pack({"manifest.json": b"{}"}))
        blob[-2 - 8 : -2] = struct.pack(">Q", 10**9)
        with pytest.raises(JobError):
            Container.unpack(bytes(blob), max_bytes=LIMIT)

    @pytest.mark.parametrize("cut", [3, 9, 20])
    def test_cut_short_is_refused(self, cut):
        with pytest.raises(JobError):
            Container.unpack(Container.pack({"manifest.json": b"{}"})[:cut], max_bytes=LIMIT)

    def test_trailing_data_is_refused(self):
        with pytest.raises(JobError):
            Container.unpack(Container.pack({"manifest.json": b"{}"}) + b"x", max_bytes=LIMIT)

    def test_duplicate_names_are_refused(self):
        one = Container.pack({"manifest.json": b"{}"})
        entry = one[8:]
        doubled = one[:4] + struct.pack(">I", 2) + entry + entry
        with pytest.raises(JobError):
            Container.unpack(doubled, max_bytes=LIMIT)
