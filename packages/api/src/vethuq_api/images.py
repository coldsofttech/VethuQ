"""Pictures for the preview: a TIFF frame, a GIF, WebP or HEIC page, a BMP or a JPEG 2000 as a PNG.

Browsers draw JPEG and PNG themselves, so those are served as they are. A BMP can be run-length
encoded, OS/2 or a headerless DIB, which browsers do not all draw, so it is converted too. A GIF or
a WebP is shown one page at a time, the pages being the distinct pictures of its animation as the
GIF and WebP add-ons read them. A HEIC is shown one picture at a time, the primary one first, as the
HEIC add-on reads them; no browser but Safari draws it."""

from __future__ import annotations

import io
import warnings
from typing import Any

# A frame bigger than this is not converted (40 megapixels: a 7000 x 6000 scan).
MAX_PIXELS = 40_000_000
# The pages of an animated GIF or WebP, as their add-ons read them: its distinct pictures, at most
# this many, found in its first frames. A preview must show the picture that was read, so these
# match.
ANIMATION_MAX_PAGES = 30
ANIMATION_MAX_SCAN_FRAMES = 1000
ANIMATED = ("GIF", "WEBP")
# The pictures of a HEIC file, as the HEIC add-on reads them: the primary first, at most this many.
HEIC_MAX_PAGES = 30


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


class _Refused(ValueError):
    """A picture VethuQ will not make (it is too large): its message is for the person."""


def animated_pages(path: str, kind: str = "GIF") -> int:
    """How many pages (distinct pictures) the GIF or WebP (`kind`) has."""
    Image = _pillow(kind)
    with Image.open(path) as picture:
        return len(_distinct_frames(picture))


def gif_pages(path: str) -> int:
    """How many pages (distinct pictures) the GIF has."""
    return animated_pages(path, "GIF")


def gif_page_as_png(path: str, page: int) -> bytes:
    """Page `page` (from 1) of a GIF as PNG bytes: the picture a viewer shows at that point of the
    animation, with transparency flattened onto white as it is for OCR."""
    return _as_png(path, page, "GIF", "frame")


def webp_page_as_png(path: str, page: int) -> bytes:
    """Page `page` (from 1) of a WebP as PNG bytes: the picture a viewer shows at that point of an
    animation (a still has one page), with transparency flattened onto white as it is for OCR."""
    return _as_png(path, page, "WEBP", "frame")


def jp2_as_png(path: str) -> bytes:
    """A JPEG 2000 as PNG bytes (no browser but Safari draws it), with transparency flattened onto
    white as it is for OCR."""
    return _as_png(path, 1, "JPEG2000", "picture")


def heic_page_as_png(path: str, page: int) -> bytes:
    """Page `page` (from 1) of a HEIC as PNG bytes: its pictures with the primary one first, as
    the HEIC add-on reads them, with transparency flattened onto white as it is for OCR."""
    return _as_png(path, page, "HEIC", "picture")


def _heic_order(picture: Any) -> list[int]:
    """The indexes of a HEIC's pictures: the primary first, then the rest in file order."""
    count = max(int(getattr(picture, "n_frames", 1)), 1)
    primary = min(max(picture.tell(), 0), count - 1)
    return ([primary] + [i for i in range(count) if i != primary])[:HEIC_MAX_PAGES]


def _open(Image: Any, path: str, kind: str) -> Any:
    """The file opened as `kind`. A HEIC is opened with pillow-heif directly (it is not registered
    with Pillow), and, as pillow-heif makes no check of its own, with Pillow's limit applied."""
    if kind != "HEIC":
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return Image.open(path)
    try:
        from pillow_heif import HeifImageFile  # noqa: PLC0415 - only for these pictures
    except ImportError as error:  # pragma: no cover - the HEIC add-on needs pillow-heif
        raise _Refused("pillow-heif is not installed, so a HEIC cannot be shown here.") from error
    picture = HeifImageFile(path)
    limit = Image.MAX_IMAGE_PIXELS
    if limit is not None and picture.width * picture.height > limit:
        picture.close()
        raise Image.DecompressionBombError("too large")
    return picture


def _distinct_frames(picture: Any) -> list[int]:
    """The index of the first frame of each distinct picture, in order (see the GIF add-on)."""
    import hashlib  # noqa: PLC0415

    kept: list[int] = []
    seen: set[bytes] = set()
    for index in range(min(getattr(picture, "n_frames", 1), ANIMATION_MAX_SCAN_FRAMES)):
        picture.seek(index)
        key = hashlib.blake2b(picture.convert("RGBA").tobytes(), digest_size=16).digest()
        if key in seen:
            continue
        seen.add(key)
        kept.append(index)
        if len(kept) >= ANIMATION_MAX_PAGES:
            break
    return kept


def _as_png(path: str, frame: int, kind: str, noun: str) -> bytes:
    Image = _pillow(kind)
    from PIL import ImageOps  # noqa: PLC0415 - only for these pictures

    label = "JPEG 2000" if kind == "JPEG2000" else kind
    unreadable = ValueError(f"This {noun} cannot be read: it is damaged, or it is not a {label}.")
    # Pillow's plugins raise all sorts of errors (an IndexError, a TypeError, a struct.error...) for
    # a file that is not what it says, is cut off, or claims a size no one should allocate; every
    # one becomes a message a person can read, never a server error. Only our own refusals
    # (`_Refused`) say something else.
    try:
        picture = _open(Image, path, kind)
    except _Refused:
        raise
    except Exception as error:  # noqa: BLE001
        raise unreadable from error
    if kind == "JPEG2000" and picture.format != "JPEG2000":
        picture.close()
        raise unreadable
    with picture:
        try:
            order = None
            if kind in ANIMATED:
                order = _distinct_frames(picture)
            elif kind == "HEIC":
                order = _heic_order(picture)
            # Reading the frame count reads every frame's header, so a cut-off file fails here.
            frames = len(order) if order is not None else int(getattr(picture, "n_frames", 1))
        except Exception as error:  # noqa: BLE001
            raise unreadable from error
        if not 1 <= frame <= frames:
            raise ValueError(f"The {label} has {frames} {'frame' if frames == 1 else 'frames'}.")
        try:
            picture.seek(order[frame - 1] if order is not None else frame - 1)
            pixels = picture.width * picture.height
            if pixels > MAX_PIXELS:
                raise _Refused(
                    f"This {noun} is {pixels / 1_000_000:.0f} megapixels, too large to preview "
                    f"(the limit is {MAX_PIXELS // 1_000_000}). Open it instead."
                )
            upright = ImageOps.exif_transpose(picture)
            if upright.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
                upright = _eight_bit(upright)
            if kind == "BMP" and upright.mode == "RGBA":
                if upright.getchannel("A").getextrema() == (0, 0):
                    upright = upright.convert("RGB")
            if kind in ANIMATED or kind in ("HEIC", "JPEG2000"):
                upright = _on_white(upright)
            if upright.mode not in ("RGB", "RGBA", "L", "LA"):
                upright = upright.convert("RGBA" if "transparency" in upright.info else "RGB")
            out = io.BytesIO()
            upright.save(out, format="PNG")
        except _Refused:
            raise
        except Exception as error:  # noqa: BLE001 - a file cut off partway, found out when decoded
            raise unreadable from error
        return out.getvalue()


def _on_white(picture: Any) -> Any:
    """A picture with any transparency laid on white, as it is when OCR reads it."""
    Image = _pillow("GIF")
    if picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info:
        rgba = picture.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return picture.convert("RGB")


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
