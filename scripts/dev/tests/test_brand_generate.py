from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PIL import Image

from scripts.dev.brand.generate import BrandGenerator

LICENSE_MD = "# Title\n\n## Section\n- **bold** item\n  continued\n\nplain {text} \\ ✓\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    brand = tmp_path / "packages" / "vethuq-ui" / "src" / "vethuq_ui" / "assets" / "brand"
    installer = tmp_path / "packages" / "vethuq-ui" / "installer"
    cli = tmp_path / "packages" / "vethuq-cli" / "src" / "vethuq_cli"
    for d in (brand, installer, cli):
        d.mkdir(parents=True)
    icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    icon.paste((200, 30, 60, 255), (64, 64, 192, 192))
    icon.save(brand / "vethuq.png")
    (installer / "LICENSE.md").write_text(LICENSE_MD, encoding="utf-8")
    return tmp_path


def _gen(repo: Path) -> BrandGenerator:
    return BrandGenerator(repo_root=repo)


def test_paths_derive_from_repo_root(repo: Path) -> None:
    gen = _gen(repo)

    assert gen.brand == repo / "packages/vethuq-ui/src/vethuq_ui/assets/brand"
    assert gen.installer == repo / "packages/vethuq-ui/installer"
    assert gen.cli_logo == repo / "packages/vethuq-cli/src/vethuq_cli/logo.py"
    assert gen.master.mode == "RGBA"


def test_default_repo_root_is_the_repository() -> None:
    assert (BrandGenerator.REPO_ROOT / "scripts" / "dev" / "brand" / "generate.py").is_file()


def test_write_icon_writes_both_ico_files(repo: Path) -> None:
    gen = _gen(repo)

    gen.write_icon()

    for target in (gen.brand / "vethuq.ico", gen.installer / "vethuq.ico"):
        with Image.open(target) as ico:
            assert ico.format == "ICO"
            assert set(ico.info["sizes"]) == set(BrandGenerator.ICO_SIZES)


def test_write_wizard_images_sizes_and_flat_rgb(repo: Path) -> None:
    gen = _gen(repo)

    gen.write_wizard_images()

    for name, size in (("wizard_small.bmp", (55, 55)), ("wizard_large.bmp", (164, 314))):
        with Image.open(gen.installer / name) as bmp:
            assert bmp.size == size
            assert bmp.mode == "RGB"
            assert bmp.getpixel((0, 0)) == BrandGenerator.WIZARD_BACKGROUND


def test_on_background_centres_icon() -> None:
    icon = Image.new("RGBA", (10, 10), (255, 0, 0, 255))

    out = BrandGenerator._on_background(icon, (20, 10))

    assert out.size == (20, 10)
    assert out.getpixel((0, 5)) == BrandGenerator.WIZARD_BACKGROUND
    assert out.getpixel((10, 5)) == (255, 0, 0)


def test_write_console_logo_generates_valid_module(repo: Path) -> None:
    gen = _gen(repo)

    gen.write_console_logo()

    source = gen.cli_logo.read_text(encoding="utf-8")
    ast.parse(source)
    assert "scripts/dev/brand/generate.py" in source
    namespace: dict[str, object] = {}
    exec(compile(source, "logo.py", "exec"), namespace)  # noqa: S102
    logo = namespace["Logo"]
    assert len(logo.ROWS) == BrandGenerator.CONSOLE_COLUMNS // 2
    assert logo.markup() == "\n".join(logo.ROWS)
    # Transparent corners are blanks; the opaque centre uses half-block colour markup.
    assert logo.ROWS[0].startswith(" ")
    assert "#c81e3c" in logo.markup()


def test_write_license_produces_ascii_rtf(repo: Path) -> None:
    gen = _gen(repo)

    gen.write_license()

    rtf = (gen.installer / "LICENSE.rtf").read_text(encoding="ascii")
    assert rtf.startswith("{\\rtf1\\ansi\\deff0")
    assert rtf.endswith("}")
    assert "\\pict\\pngblip\\picw96\\pich96" in rtf
    assert "\\fs34\\b Title" in rtf
    assert "\\fs26\\b Section" in rtf
    assert "\\bullet" in rtf
    assert "{\\b bold} item" in rtf
    assert "\\li560 continued" in rtf


def test_write_license_escapes_special_characters(repo: Path) -> None:
    gen = _gen(repo)

    gen.write_license()

    rtf = (gen.installer / "LICENSE.rtf").read_text(encoding="ascii")
    assert "\\{text\\}" in rtf
    assert "\\\\" in rtf
    assert "\\u10003?" in rtf  # U+2713


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "plain"),
        ("a{b}c", "a\\{b\\}c"),
        ("back\\slash", "back\\\\slash"),
        ("é", "\\u233?"),
        ("￿", "\\u-1?"),
    ],
)
def test_rtf_escape(text: str, expected: str) -> None:
    assert BrandGenerator._rtf_escape(text) == expected


def test_inline_renders_bold() -> None:
    assert BrandGenerator._inline("a **b** c") == "a {\\b b} c"


def test_cw_prefixes_each_word() -> None:
    assert BrandGenerator._cw("b", "fs34") == "\\b\\fs34"


def test_run_writes_every_asset(repo: Path) -> None:
    gen = _gen(repo)

    gen.run()

    for path in (
        gen.brand / "vethuq.ico",
        gen.installer / "vethuq.ico",
        gen.installer / "wizard_small.bmp",
        gen.installer / "wizard_large.bmp",
        gen.installer / "LICENSE.rtf",
        gen.cli_logo,
    ):
        assert path.is_file()


def test_run_is_deterministic(repo: Path) -> None:
    gen = _gen(repo)
    gen.run()
    first = {p: p.read_bytes() for p in (gen.installer / "LICENSE.rtf", gen.cli_logo)}

    gen.run()

    assert {p: p.read_bytes() for p in first} == first
