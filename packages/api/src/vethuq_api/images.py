"""Pictures for the preview: a TIFF frame as a PNG a browser can show (browsers draw JPEG and PNG
themselves, so those are served as they are)."""

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
    Image = _pillow()
    from PIL import ImageOps  # noqa: PLC0415 - Pillow is only needed for a TIFF

    with Image.open(path) as picture:
        frames = int(getattr(picture, "n_frames", 1))
        if not 1 <= frame <= frames:
            raise ValueError(f"The TIFF has {frames} {'frame' if frames == 1 else 'frames'}.")
        picture.seek(frame - 1)
        pixels = picture.width * picture.height
        if pixels > MAX_PIXELS:
            raise ValueError(
                f"This frame is {pixels / 1_000_000:.0f} megapixels, too large to preview "
                f"(the limit is {MAX_PIXELS // 1_000_000}). Open it instead."
            )
        upright = ImageOps.exif_transpose(picture)
        if upright.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            upright = _eight_bit(upright)
        if upright.mode not in ("RGB", "RGBA", "L", "LA"):
            upright = upright.convert("RGBA" if "transparency" in upright.info else "RGB")
        out = io.BytesIO()
        upright.save(out, format="PNG")
        return out.getvalue()


def _eight_bit(picture: Any) -> Any:
    """A 16-bit or floating point grey picture scaled down to 8 bits (its own range to 0-255)."""
    low, high = picture.getextrema()
    scale = 255.0 / (high - low) if high > low else 1.0
    return picture.point(lambda v: (v - low) * scale).convert("L")


def _pillow() -> Any:
    try:
        from PIL import Image  # noqa: PLC0415 - only needed for a TIFF
    except ImportError as error:  # pragma: no cover - the TIFF add-on needs Pillow
        raise ValueError("Pillow is not installed, so a TIFF cannot be shown here.") from error
    return Image
