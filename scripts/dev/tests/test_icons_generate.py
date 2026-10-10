from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from scripts.dev.icons.generate import IconGenerator

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
    'viewBox="0 0 16 16" fill="currentColor"><rect x="2" y="2" width="12" height="12"/></svg>'
)


def _can_render() -> bool:
    try:
        IconGenerator._render_icon(SVG, 16, "#1976d2")
    except Exception:
        return False
    return True


class TestIconGenerator:
    @staticmethod
    def _stub_render(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, str | None]]:
        calls: list[tuple[str, int, str | None]] = []

        def fake(svg_text: str, size: int, color: str | None) -> Image.Image:
            calls.append((svg_text, size, color))
            return Image.new("RGBA", (size, size), (1, 2, 3, 255))

        monkeypatch.setattr(IconGenerator, "_render_icon", staticmethod(fake))
        return calls

    @staticmethod
    def _write_manifest(directory: Path, entries: list[dict[str, Any]]) -> Path:
        (directory / "a.svg").write_text(SVG, encoding="utf-8")
        manifest = directory / "icons.json"
        manifest.write_text(json.dumps(entries), encoding="utf-8")
        return manifest

    # --- _recolor_svg -----------------------------------------------------

    @pytest.mark.parametrize(
        "fill", ["currentColor", "CURRENTCOLOR", "#000", "#000000", "black", "BLACK"]
    )
    def test_recolor_replaces_recolorable_fill(self, fill: str) -> None:
        svg = f'<svg fill="{fill}"><path d="M0 0"/></svg>'

        assert IconGenerator._recolor_svg(svg, "#1976d2") == (
            '<svg fill="#1976d2"><path d="M0 0"/></svg>'
        )

    def test_recolor_replaces_every_match(self) -> None:
        svg = '<svg fill="currentColor"><path fill="black"/></svg>'

        out = IconGenerator._recolor_svg(svg, "#fff000")

        assert out.count('fill="#fff000"') == 2

    def test_recolor_injects_fill_when_root_has_none(self) -> None:
        out = IconGenerator._recolor_svg('<svg width="16"><path/></svg>', "#123456")

        assert out == '<svg width="16" fill="#123456"><path/></svg>'

    def test_recolor_keeps_unrecolorable_existing_fill(self) -> None:
        svg = '<svg fill="#ff0000"><path/></svg>'

        assert IconGenerator._recolor_svg(svg, "#123456") == svg

    # --- _hex_to_rgb ------------------------------------------------------

    @pytest.mark.parametrize(
        ("color", "rgb"),
        [("#1976d2", (25, 118, 210)), ("d32f2f", (211, 47, 47)), ("#000000", (0, 0, 0))],
    )
    def test_hex_to_rgb(self, color: str, rgb: tuple[int, int, int]) -> None:
        assert IconGenerator._hex_to_rgb(color) == rgb

    # --- _white_background_to_alpha ---------------------------------------

    def test_alpha_with_color_solves_blend_toward_white(self) -> None:
        fg = (0, 0, 255)
        image = Image.new("RGB", (3, 1))
        image.putpixel((0, 0), (255, 255, 255))  # pure background
        image.putpixel((1, 0), (0, 0, 255))  # pure glyph
        image.putpixel((2, 0), (128, 128, 255))  # half blended toward white

        out = IconGenerator._white_background_to_alpha(image, "#0000ff")

        assert out.mode == "RGBA"
        assert out.getpixel((0, 0)) == (*fg, 0)
        assert out.getpixel((1, 0)) == (*fg, 255)
        assert out.getpixel((2, 0)) == (*fg, 127)

    def test_alpha_with_white_color_does_not_divide_by_zero(self) -> None:
        out = IconGenerator._white_background_to_alpha(
            Image.new("RGB", (1, 1), (255, 255, 255)), "#ffffff"
        )

        assert out.getpixel((0, 0)) == (255, 255, 255, 0)

    def test_alpha_without_color_uses_near_white_cutoff(self) -> None:
        image = Image.new("RGB", (3, 1))
        image.putpixel((0, 0), (255, 255, 255))
        image.putpixel((1, 0), (250, 250, 250))
        image.putpixel((2, 0), (249, 250, 250))

        out = IconGenerator._white_background_to_alpha(image, None)

        assert out.getpixel((0, 0))[3] == 0
        assert out.getpixel((1, 0))[3] == 0
        assert out.getpixel((2, 0)) == (249, 250, 250, 255)

    # --- generate_one / generate_all --------------------------------------

    def test_generate_one_recolors_sizes_and_saves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._stub_render(monkeypatch)
        manifest = self._write_manifest(tmp_path, [])
        out_dir = tmp_path / "out" / "nested"
        entry = {"name": "search", "svg": "a.svg", "color": "#1976d2", "size": 24}

        path = IconGenerator(out_dir=out_dir).generate_one(entry, manifest.parent)

        assert path == out_dir / "search.png"
        with Image.open(path) as png:
            assert png.size == (24, 24)
        svg_text, size, color = calls[0]
        assert 'fill="#1976d2"' in svg_text
        assert (size, color) == (24, "#1976d2")

    def test_generate_one_defaults_size_and_keeps_source_colors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._stub_render(monkeypatch)
        manifest = self._write_manifest(tmp_path, [])

        IconGenerator(out_dir=tmp_path / "out").generate_one(
            {"name": "plain", "svg": "a.svg"}, manifest.parent
        )

        assert calls == [(SVG, IconGenerator.DEFAULT_SIZE, None)]

    def test_generate_one_resolves_svg_relative_to_manifest_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_render(monkeypatch)
        (tmp_path / "svgs").mkdir()
        (tmp_path / "svgs" / "x.svg").write_text(SVG, encoding="utf-8")

        path = IconGenerator(out_dir=tmp_path / "out").generate_one(
            {"name": "x", "svg": "svgs/x.svg"}, tmp_path
        )

        assert path.is_file()

    def test_generate_one_missing_svg_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            IconGenerator(out_dir=tmp_path / "out").generate_one(
                {"name": "x", "svg": "missing.svg"}, tmp_path
            )

    def test_generate_all_writes_each_entry_and_reports(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._stub_render(monkeypatch)
        manifest = self._write_manifest(
            tmp_path,
            [{"name": "one", "svg": "a.svg"}, {"name": "two", "svg": "a.svg", "size": 32}],
        )
        out_dir = tmp_path / "out"

        written = IconGenerator(out_dir=out_dir).generate_all(manifest)

        assert written == [out_dir / "one.png", out_dir / "two.png"]
        assert capsys.readouterr().out.splitlines() == [f"wrote {p}" for p in written]

    # --- main -------------------------------------------------------------

    def test_main_uses_manifest_and_out_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_render(monkeypatch)
        manifest = self._write_manifest(tmp_path, [{"name": "one", "svg": "a.svg"}])
        out_dir = tmp_path / "out"

        code = IconGenerator.main(["--manifest", str(manifest), "--out-dir", str(out_dir)])

        assert code == 0
        assert (out_dir / "one.png").is_file()

    def test_main_requires_manifest(self) -> None:
        with pytest.raises(SystemExit):
            IconGenerator.main([])

    def test_default_out_dir_is_vethuq_ui_assets(self) -> None:
        expected = IconGenerator.REPO_ROOT.joinpath(
            "packages", "vethuq-ui", "src", "vethuq_ui", "assets", "icons"
        )
        assert expected == IconGenerator.DEFAULT_OUT_DIR
        assert (IconGenerator.REPO_ROOT / "scripts" / "dev" / "icons" / "generate.py").is_file()

    # --- real rendering (needs svglib + a working reportlab renderer) -----

    @pytest.mark.skipif(not _can_render(), reason="svglib/reportlab PNG rendering unavailable")
    def test_real_render_produces_transparent_recoloured_png(self, tmp_path: Path) -> None:
        manifest = self._write_manifest(
            tmp_path, [{"name": "box", "svg": "a.svg", "color": "#1976d2", "size": 32}]
        )

        (path,) = IconGenerator(out_dir=tmp_path / "out").generate_all(manifest)

        with Image.open(path) as png:
            assert png.size == (32, 32)
            assert png.getpixel((0, 0))[3] == 0
            assert png.getpixel((16, 16)) == (25, 118, 210, 255)
