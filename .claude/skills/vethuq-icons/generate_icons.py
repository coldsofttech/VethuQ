"""Turn SVG icon sources into the PNG assets vethuq-ui ships.

Not part of the vethuq-ui package - a design-time tool for the
`vethuq-icons` skill. Its deps (svglib, reportlab, pillow) are pinned in
the repo root `pyproject.toml`'s `dev` dependency-group, so a plain
`uv sync` picks them up and this just runs directly:

    uv run python .claude/skills/vethuq-icons/generate_icons.py \
        --manifest icons.json

reportlab is pinned to 3.6.13 deliberately: newer reportlab's PNG renderer
needs rlPyCairo -> pycairo -> the native Cairo library, which isn't
installed on a plain Windows dev box (no system package manager provides
it). 3.6.13 ships its own bundled `_renderPM` extension and needs nothing
else system-side. cairosvg was tried first and hits the same native-Cairo
wall - don't reach for it here. Don't bump reportlab past 3.6.13 without
re-verifying PNG output works without Cairo installed.

The manifest is a JSON list of icons to (re)generate:

    [
      {"name": "search", "svg": "search.svg", "color": "#1976d2"},
      {"name": "pdf", "svg": "filetype-pdf.svg", "color": "#d32f2f", "size": 16}
    ]

Fields:
  name   output filename stem -> "<out-dir>/<name>.png"          (required)
  svg    path to the source SVG, resolved relative to the         (required)
         manifest file's own directory
  color  hex color (e.g. "#1976d2") to recolor the glyph to and    (optional)
         to key the background out to transparent against.
         Omitting it keeps the source SVG's own colors, but then
         background removal falls back to a plain near-white
         cutoff instead of a clean alpha gradient - pass a color
         whenever the icon is a flat single-color glyph.
  size   final PNG size in pixels, square                          (optional, default 16)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

_DEFAULT_SIZE = 16
_BASE_RENDER_SIZE = 128
_NEAR_WHITE_THRESHOLD = 250

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUT_DIR = _REPO_ROOT / "packages" / "vethuq-ui" / "src" / "vethuq_ui" / "assets" / "icons"

_RECOLORABLE_FILL_RE = re.compile(r'fill="(currentColor|#000000?|#000|black)"', re.IGNORECASE)


def _recolor_svg(svg_text: str, color: str) -> str:
    """Force every recolorable fill in `svg_text` to `color`.

    Bootstrap Icons (and most single-color icon sets) put `fill="currentColor"`
    on the root <svg> and leave child <path> elements uncolored, so overriding
    that one attribute recolors the whole glyph. If the root <svg> has no fill
    at all, inject one instead of leaving it black-by-default.
    """
    recolored, count = _RECOLORABLE_FILL_RE.subn(f'fill="{color}"', svg_text)
    if count == 0:
        head, sep, rest = recolored.partition(">")
        if "fill=" not in head:
            recolored = f'{head} fill="{color}"{sep}{rest}'
    return recolored


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _white_background_to_alpha(image: Any, color: str | None) -> Any:
    """Recover an alpha channel from a flat-color glyph rendered on white.

    reportlab's PNG output has no transparency support in the 3.6.x branch
    we're pinned to, so every render comes back as an opaque white square.
    When the glyph's color is known, each pixel's alpha is solved for
    exactly from how far that pixel has been blended toward white; without
    a known color this falls back to a hard near-white cutoff, which is
    cruder (jagged edges) but still usable.
    """
    from PIL import Image

    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    pixels = rgb_image.load()
    out = Image.new("RGBA", (width, height))
    out_pixels = out.load()

    if color:
        fg = _hex_to_rgb(color)
        channel = max(range(3), key=lambda c: 255 - fg[c])
        denom = max(1, 255 - fg[channel])
        for y in range(height):
            for x in range(width):
                level = pixels[x, y][channel]
                alpha = max(0, min(255, round((255 - level) / denom * 255)))
                out_pixels[x, y] = (*fg, alpha)
    else:
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]
                is_background = (
                    r >= _NEAR_WHITE_THRESHOLD
                    and g >= _NEAR_WHITE_THRESHOLD
                    and b >= _NEAR_WHITE_THRESHOLD
                )
                out_pixels[x, y] = (r, g, b, 0 if is_background else 255)

    return out


def _render_icon(svg_text: str, size: int, color: str | None) -> Any:
    from PIL import Image
    from reportlab.graphics import renderPM
    from svglib.svglib import svg2rlg

    drawing = svg2rlg(BytesIO(svg_text.encode("utf-8")))
    scale = _BASE_RENDER_SIZE / drawing.width
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)

    png_bytes = BytesIO()
    renderPM.drawToFile(drawing, png_bytes, fmt="PNG")
    png_bytes.seek(0)

    image = Image.open(png_bytes)
    image = _white_background_to_alpha(image, color)
    if size != _BASE_RENDER_SIZE:
        image = image.resize((size, size), Image.LANCZOS)
    return image


def _generate_one(entry: dict[str, Any], manifest_dir: Path, out_dir: Path) -> Path:
    name = entry["name"]
    svg_path = (manifest_dir / entry["svg"]).resolve()
    color = entry.get("color")
    size = int(entry.get("size", _DEFAULT_SIZE))

    svg_text = svg_path.read_text(encoding="utf-8")
    if color:
        svg_text = _recolor_svg(svg_text, color)

    image = _render_icon(svg_text, size, color)
    out_path = out_dir / f"{name}.png"
    out_dir.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", required=True, type=Path, help="Path to the icons manifest JSON."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
        help="Where to write the generated PNGs (default: vethuq-ui's assets/icons).",
    )
    args = parser.parse_args()

    manifest_path: Path = args.manifest.resolve()
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))

    for entry in entries:
        out_path = _generate_one(entry, manifest_path.parent, args.out_dir)
        print(f"wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
