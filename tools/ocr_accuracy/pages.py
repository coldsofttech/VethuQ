"""Pages rendered from known text, and the degradations scans and photos add to them.

A page is made from a fixed text, so what a read should say is known exactly. Everything is
deterministic (a seed drives the noise), so a change in the scores is a change in the engine.
Fonts come from the operating system (set `VETHUQ_ACCURACY_FONT_<LANG>` to a font file to choose
one); a language whose font is missing raises `FontNotFound` and its cases are skipped.

To add a page type: write a function from the clean image to the degraded one, list it in
`DEGRADE`, and give it limits in `thresholds.json`. To add a language: add its texts to `TEXTS`
and its font candidates to `FONTS`.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

PROSE = {
    "en": [
        "The quarterly review of the archive was finished on a quiet Tuesday morning.",
        "Every document in the cabinet had been scanned, numbered and filed by subject.",
        "Maria Gonzalez checked the totals twice before she signed the final report.",
        "A short note on the first page explained how the records were organised.",
        "Letters from the northern office arrived late, but none of them were missing.",
        "The committee agreed that old invoices should be kept for seven years.",
        "Please return the blue folder to the reception desk before five o'clock.",
        "Reading a printed page should give back exactly the words that were written.",
        "Small differences between a letter and its neighbour are where mistakes begin.",
        "The final paragraph thanks everyone who helped to prepare these papers.",
    ]
}
NUMBERS = {
    "en": [
        "Invoice 2024-00137  Date 14/03/2024  Customer 58213",
        "Item 1   Paper A4 (500 sheets)   12 x 4.50   54.00",
        "Item 2   Toner cartridge 7B   2 x 89.95   179.90",
        "Item 3   Delivery and handling   1 x 12.50   12.50",
        "Subtotal 246.40   VAT 20%  49.28   Total 295.68",
        "Account 0043 1187 5521 9034   Reference 70-4419-82",
        "Phone +44 20 7946 0958   Order 3 of 17   Weight 12.4 kg",
    ]
}
FONTS = {
    "en": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
}

A4_150 = (1240, 1754)  # A4 at 150 dpi
A4_300 = (2480, 3508)  # A4 at 300 dpi
MARGIN = 0.08


class FontNotFound(LookupError):
    """No font file for the language was found."""


@dataclass(frozen=True)
class Page:
    """An image (BGR, uint8, as OCR engines take it) and the text it was rendered from."""

    page_type: str
    language: str
    reference: str
    image: np.ndarray


def find_font(language: str) -> str:
    chosen = os.environ.get(f"VETHUQ_ACCURACY_FONT_{language.upper()}")
    for candidate in [chosen, *FONTS.get(language, [])]:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FontNotFound(f"No font for {language!r}: set VETHUQ_ACCURACY_FONT_{language.upper()}.")


def wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Break a line at spaces so that no piece is wider than `width` pixels."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        trial = f"{current} {word}" if current else word
        if current and font.getlength(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    return [*lines, current]


def render(
    lines: list[str], language: str, size: tuple[int, int], font_px: int
) -> tuple[Image.Image, list[str]]:
    """Black text on white from the top-left margin, wrapped to the page. Returns the image and
    the lines as they were drawn: what a read should give back."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(find_font(language), font_px)
    x, y = int(size[0] * MARGIN), int(size[1] * MARGIN)
    drawn: list[str] = []
    for line in lines:
        for piece in wrap(line, font, size[0] * (1 - 2 * MARGIN)):
            draw.text((x, y), piece, fill="black", font=font)
            drawn.append(piece)
            y += int(font_px * 1.6)
    return image, drawn


# ----- degradations ----------------------------------------------------------------------------


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")


def _noise(image: Image.Image, sigma: float, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    pixels = np.asarray(image, dtype=np.float32)
    pixels = pixels + rng.normal(0.0, sigma, pixels.shape[:2] + (1,))
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))


def scan(image: Image.Image, seed: int) -> Image.Image:
    """A flatbed scan: slightly soft, grainy, JPEG compressed."""
    return _jpeg(_noise(image.filter(ImageFilter.GaussianBlur(1.2)), 12, seed), 55)


def skew(image: Image.Image, seed: int) -> Image.Image:
    """The page 5 degrees off square."""
    return image.rotate(5, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))


def poor(image: Image.Image, seed: int) -> Image.Image:
    """Low resolution, low contrast, noisy and heavily compressed."""
    small = image.resize(
        (int(image.width * 0.35), int(image.height * 0.35)), Image.Resampling.BILINEAR
    )
    flat = ImageEnhance.Contrast(small.resize(image.size, Image.Resampling.BILINEAR)).enhance(0.45)
    return _jpeg(_noise(flat, 8, seed), 40)


def _coefficients(target: list[tuple[float, float]], source: list[tuple[float, float]]):
    rows, values = [], []
    for (x, y), (u, v) in zip(target, source, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.extend([u, v])
    return np.linalg.solve(np.array(rows, dtype=np.float64), np.array(values, dtype=np.float64))


def photo(image: Image.Image, seed: int) -> Image.Image:
    """A phone photo: perspective, uneven light, a little blur, JPEG."""
    w, h = image.size
    inset = 0.04
    shifted = [(w * inset, h * 0.01), (w * (1 - 0.01), h * 0.0), (w, h), (0.0, h * (1 - inset))]
    corners = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    warped = image.transform(
        image.size,
        Image.Transform.PERSPECTIVE,
        tuple(_coefficients(shifted, corners)),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(235, 235, 235),
    )
    light = np.linspace(0.62, 1.0, w, dtype=np.float32)[None, :, None]
    lit = np.clip(np.asarray(warped, dtype=np.float32) * light, 0, 255).astype(np.uint8)
    return _jpeg(Image.fromarray(lit).filter(ImageFilter.GaussianBlur(0.8)), 70)


def rotated(image: Image.Image, seed: int) -> Image.Image:
    """The page upside down."""
    return image.rotate(180)


def clean(image: Image.Image, seed: int) -> Image.Image:
    return image


DEGRADE: dict[str, Callable[[Image.Image, int], Image.Image]] = {
    "clean": clean,
    "scan": scan,
    "skew": skew,
    "poor": poor,
    "photo": photo,
    "rotated": rotated,
    "small": clean,  # small type: a smaller font on a clean page
    "numbers": clean,  # an invoice-like page of figures
    "large": clean,  # A4 at 300 dpi: the size that once ran out of memory
}
PAGE_TYPES = tuple(DEGRADE)


def make(page_type: str, language: str = "en", seed: int = 0) -> Page:
    """The page of `page_type` in `language`. Raises `KeyError` for an unknown type and
    `FontNotFound` when the language has no font here."""
    degrade = DEGRADE[page_type]
    if language not in PROSE:
        raise KeyError(f"No texts for language {language!r}.")
    lines = NUMBERS[language] if page_type == "numbers" else PROSE[language]
    size, font_px = A4_150, 34
    if page_type == "small":
        font_px = 18
    elif page_type == "large":
        size, font_px = A4_300, 68
    elif page_type == "numbers":
        font_px = 36
    flat, drawn = render(lines, language, size, font_px)
    pixels = np.asarray(degrade(flat, seed).convert("RGB"))[:, :, ::-1]  # RGB to BGR
    return Page(page_type, language, "\n".join(drawn), np.ascontiguousarray(pixels))
