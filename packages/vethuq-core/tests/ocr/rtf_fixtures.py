"""Builders for tiny RTF files, so tests don't need binary fixtures."""

from __future__ import annotations

from pathlib import Path


def rtf_picture(data: bytes, kind: str = "pngblip", *, uid: bool = True) -> str:
    blip = "{\\*\\blipuid 0123456789abcdef0123456789abcdef}" if uid else ""
    return f"{{\\pict{blip}\\{kind}\\picw120\\pich80\\picwgoal1800\\pichgoal1200\n{data.hex()}}}"


def write_rtf(path: Path, body: str) -> Path:
    path.write_bytes(
        (
            f"{{\\rtf1\\ansi\\ansicpg1252\\deff0{{\\fonttbl{{\\f0 Arial;}}}}\\f0\\fs24 {body}}}"
        ).encode("latin-1")
    )
    return path
