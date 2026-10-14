"""Pictures for the preview: a TIFF frame or a BMP as a PNG a browser can show (browsers draw JPEG
and PNG themselves, so those are served as they are; a BMP can be run-length encoded, OS/2 or a
headerless DIB, which browsers do not all draw, so it is converted too)."""

from __future__ import annotations

import io
from typing import Any

# A frame bigger than this is not converted (40 megapixels: a 7000 x 6000 scan).
MAX_PIXELS = 40_000_000


def tiff_frames(path: str) -> int:
    """How many frames (pages) the TIFF has."""
    Image = _pillow()
    with Image.open(path) as picture:
        return int(getattr(picture, "n_frames", 1))


def tiff_frame_as_png(path: str, frame: int) -> bytes:
    """Frame `frame` (from 1) of a TIFF as PNG bytes: turned upright by its orientation tag, and
    brought to ordinary 8-bit colour (16-bit, CMYK, palette and transparent frames included)."""
    return _as_png(path, frame, "TIFF", "frame")


def bmp_as_png(path: str) -> bytes:
    """A BMP (or DIB) as PNG bytes, in ordinary 8-bit colour. A 32-bit one whose alpha bytes are
    all zero (a program left the fourth byte unused) is shown opaque, not as a blank picture."""
    return _as_png(path, 1, "BMP", "picture")


def _as_png(path: str, frame: int, kind: str, noun: str) -> bytes:
    Image = _pillow(kind)
    from PIL import ImageOps, UnidentifiedImageError  # noqa: PLC0415 - only for these pictures

    unreadable = ValueError(f"This {noun} cannot be read: it is damaged, or it is not a {kind}.")
    # What Pillow raises for a file that is not what it says, is cut off, or claims a size no one
    # should allocate; each becomes a message a person can read.
    damaged = (UnidentifiedImageError, OSError, SyntaxError, EOFError, Image.DecompressionBombError)
    try:
        picture = Image.open(path)
    except damaged as error:
        raise unreadable from error
    with picture:
        frames = int(getattr(picture, "n_frames", 1))
        if not 1 <= frame <= frames:
            raise ValueError(f"The {kind} has {frames} {'frame' if frames == 1 else 'frames'}.")
        try:
            picture.seek(frame - 1)
            pixels = picture.width * picture.height
            if pixels > MAX_PIXELS:
                raise ValueError(
                    f"This {noun} is {pixels / 1_000_000:.0f} megapixels, too large to preview "
                    f"(the limit is {MAX_PIXELS // 1_000_000}). Open it instead."
                )
            upright = ImageOps.exif_transpose(picture)
            if upright.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
                upright = _eight_bit(upright)
            if kind == "BMP" and upright.mode == "RGBA":
                if upright.getchannel("A").getextrema() == (0, 0):
                    upright = upright.convert("RGB")
            if upright.mode not in ("RGB", "RGBA", "L", "LA"):
                upright = upright.convert("RGBA" if "transparency" in upright.info else "RGB")
            out = io.BytesIO()
            upright.save(out, format="PNG")
        except damaged as error:  # a file cut off partway, found out when it is decoded
            raise unreadable from error
        return out.getvalue()


def _eight_bit(picture: Any) -> Any:
    """A 16-bit or floating point grey picture scaled down to 8 bits (its own range to 0-255)."""
    low, high = picture.getextrema()
    scale = 255.0 / (high - low) if high > low else 1.0
    return picture.point(lambda v: (v - low) * scale).convert("L")


def _pillow(kind: str = "TIFF") -> Any:
    try:
        from PIL import Image  # noqa: PLC0415 - only needed for these pictures
    except ImportError as error:  # pragma: no cover - the image add-ons need Pillow
        raise ValueError(f"Pillow is not installed, so a {kind} cannot be shown here.") from error
    return Image
