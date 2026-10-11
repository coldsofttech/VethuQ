"""Packing named byte strings into one: the manifest and the page images of a job."""

from __future__ import annotations

import re
import struct

from vethuq_worker.errors import JobError

MAGIC = b"VQC1"
_NAME = re.compile(r"^(manifest\.json|images/[0-9]{1,6}\.png)$")


def pack(entries: dict[str, bytes]) -> bytes:
    out = [MAGIC, struct.pack(">I", len(entries))]
    for name, data in entries.items():
        raw = name.encode()
        out.append(struct.pack(">H", len(raw)) + raw + struct.pack(">Q", len(data)))
        out.append(data)
    return b"".join(out)


def unpack(blob: bytes, *, max_bytes: int) -> dict[str, bytes]:
    """The entries of `pack`'s output. Names are checked (no paths outside the job) and the total
    size is held to `max_bytes` before anything is copied."""

    def bad(why: str) -> JobError:
        return JobError("bad_payload", f"The job container is malformed: {why}.")

    if len(blob) > max_bytes + 1024 * 1024 or not blob.startswith(MAGIC) or len(blob) < 8:
        raise bad("wrong size or format")
    (count,) = struct.unpack_from(">I", blob, 4)
    position, total, entries = 8, 0, {}
    for _ in range(count):
        if position + 2 > len(blob):
            raise bad("cut short")
        (name_size,) = struct.unpack_from(">H", blob, position)
        position += 2
        name = blob[position : position + name_size].decode("utf-8", "replace")
        position += name_size
        if not _NAME.match(name) or name in entries:
            raise bad("unexpected entry name")
        if position + 8 > len(blob):
            raise bad("cut short")
        (size,) = struct.unpack_from(">Q", blob, position)
        position += 8
        total += size
        if total > max_bytes or position + size > len(blob):
            raise bad("entry sizes")
        entries[name] = blob[position : position + size]
        position += size
    if position != len(blob):
        raise bad("trailing data")
    return entries
