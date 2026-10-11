"""Encryption of job payloads and results.

A file is `VQJ1`, a 16-byte salt, then chunks. Each chunk is a 4-byte length and an AES-256-GCM
ciphertext. The key is derived (HKDF-SHA256) from the master key, the salt, the purpose
(`payload` or `result`) and the job id, so no two files share a key. The nonce is the chunk's
index; the additional data binds the job id, the index and whether the chunk is the last, so
chunks can't be reordered, dropped from the end or moved to another job.
"""

from __future__ import annotations

import base64
import binascii
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from vethuq_worker.errors import JobError

MAGIC = b"VQJ1"
SALT_SIZE = 16
CHUNK_SIZE = 1024 * 1024
KEY_SIZE = 32


def decode_key(text: str | bytes) -> bytes:
    """The raw key from its text form (URL-safe base64, as the setup stores it)."""
    value = text.decode("ascii", "replace") if isinstance(text, bytes) else text
    value = value.strip()
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != KEY_SIZE:
        raise JobError("bad_key", "The master key isn't a valid 256-bit key.")
    return raw


def encode_key(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_key() -> str:
    return encode_key(os.urandom(KEY_SIZE))


def _derive(master: bytes, salt: bytes, purpose: str, job_id: str) -> AESGCM:
    info = f"vethuq/v1/{purpose}/{job_id}".encode()
    return AESGCM(HKDF(hashes.SHA256(), KEY_SIZE, salt, info).derive(master))


def _nonce(index: int) -> bytes:
    return struct.pack(">QI", index, 0)


def _aad(job_id: str, index: int, last: bool) -> bytes:
    return job_id.encode() + struct.pack(">QB", index, 1 if last else 0)


def seal(master_key: str | bytes, purpose: str, job_id: str, data: bytes) -> bytes:
    """Encrypt `data` for `job_id`."""
    salt = os.urandom(SALT_SIZE)
    aead = _derive(decode_key(master_key), salt, purpose, job_id)
    pieces = [data[i : i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)] or [b""]
    out = [MAGIC, salt]
    for index, piece in enumerate(pieces):
        last = index == len(pieces) - 1
        cipher = aead.encrypt(_nonce(index), piece, _aad(job_id, index, last))
        out.append(struct.pack(">I", len(cipher)))
        out.append(cipher)
    return b"".join(out)


def open_sealed(master_key: str | bytes, purpose: str, job_id: str, blob: bytes) -> bytes:
    """Decrypt what `seal` made. Raises `JobError("bad_payload")` for anything altered, cut short,
    made for another job or key."""
    bad = JobError("bad_payload", "The data can't be decrypted: wrong key or altered data.")
    if len(blob) < len(MAGIC) + SALT_SIZE or not blob.startswith(MAGIC):
        raise JobError("bad_payload", "The data isn't a VethuQ job file.")
    aead = _derive(decode_key(master_key), blob[4 : 4 + SALT_SIZE], purpose, job_id)
    position, index, out = 4 + SALT_SIZE, 0, []
    while True:
        if position + 4 > len(blob):
            raise bad
        (size,) = struct.unpack_from(">I", blob, position)
        position += 4
        if size < 16 or position + size > len(blob):
            raise bad
        cipher = blob[position : position + size]
        position += size
        last = position == len(blob)
        try:
            out.append(aead.decrypt(_nonce(index), cipher, _aad(job_id, index, last)))
        except InvalidTag:
            raise bad from None
        if last:
            return b"".join(out)
        index += 1
