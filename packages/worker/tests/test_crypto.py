from __future__ import annotations

import pytest

from vethuq_worker import crypto
from vethuq_worker.errors import JobError

KEY = crypto.generate_key()


class TestKeys:
    def test_generated_key_decodes_to_256_bits(self):
        assert len(crypto.decode_key(KEY)) == 32

    @pytest.mark.parametrize("bad", ["", "short", "!!!!", "A" * 10])
    def test_bad_keys_are_refused(self, bad):
        with pytest.raises(JobError) as caught:
            crypto.decode_key(bad)
        assert caught.value.code == "bad_key"

    def test_encode_decode_roundtrip(self):
        raw = bytes(range(32))
        assert crypto.decode_key(crypto.encode_key(raw)) == raw


class TestSeal:
    def test_roundtrip(self):
        blob = crypto.seal(KEY, "payload", "job-00000001", b"hello")
        assert b"hello" not in blob
        assert crypto.open_sealed(KEY, "payload", "job-00000001", blob) == b"hello"

    def test_empty_data_roundtrips(self):
        blob = crypto.seal(KEY, "payload", "job-00000001", b"")
        assert crypto.open_sealed(KEY, "payload", "job-00000001", blob) == b""

    def test_multi_chunk_roundtrip(self):
        data = bytes(range(256)) * (crypto.CHUNK_SIZE // 256 * 2 + 3)
        blob = crypto.seal(KEY, "payload", "job-00000001", data)
        assert crypto.open_sealed(KEY, "payload", "job-00000001", blob) == data

    def test_two_seals_of_the_same_data_differ(self):
        a = crypto.seal(KEY, "payload", "job-00000001", b"x")
        b = crypto.seal(KEY, "payload", "job-00000001", b"x")
        assert a != b

    @pytest.mark.parametrize(
        "change",
        [
            lambda blob: blob[:-1] + bytes([blob[-1] ^ 1]),
            lambda blob: blob[:30] + bytes([blob[30] ^ 1]) + blob[31:],
            lambda blob: blob[:-5],
            lambda blob: blob[:10],
            lambda blob: b"XXXX" + blob[4:],
            lambda blob: blob + b"\x00",
        ],
    )
    def test_altered_data_is_refused(self, change):
        blob = crypto.seal(KEY, "payload", "job-00000001", b"hello")
        with pytest.raises(JobError) as caught:
            crypto.open_sealed(KEY, "payload", "job-00000001", change(blob))
        assert caught.value.code == "bad_payload"

    def test_wrong_key_job_or_purpose_is_refused(self):
        blob = crypto.seal(KEY, "payload", "job-00000001", b"hello")
        for key, purpose, job in [
            (crypto.generate_key(), "payload", "job-00000001"),
            (KEY, "result", "job-00000001"),
            (KEY, "payload", "job-00000002"),
        ]:
            with pytest.raises(JobError):
                crypto.open_sealed(key, purpose, job, blob)

    def test_dropping_the_last_chunk_is_detected(self):
        data = b"a" * (crypto.CHUNK_SIZE * 2)
        blob = crypto.seal(KEY, "payload", "job-00000001", data)
        first_chunk_end = 20 + 4 + crypto.CHUNK_SIZE + 16
        with pytest.raises(JobError):
            crypto.open_sealed(KEY, "payload", "job-00000001", blob[:first_chunk_end])

    def test_reordered_chunks_are_detected(self):
        size = 4 + crypto.CHUNK_SIZE + 16
        blob = crypto.seal(KEY, "payload", "job-00000001", b"a" * crypto.CHUNK_SIZE + b"b" * 5)
        head, first, second = blob[:20], blob[20 : 20 + size], blob[20 + size :]
        with pytest.raises(JobError):
            crypto.open_sealed(KEY, "payload", "job-00000001", head + second + first)
