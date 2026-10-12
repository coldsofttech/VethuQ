"""Derive the CLI installer's images from the master icon, `icons/icon-512.png`.

Writes the Windows `.ico`, the Inno Setup wizard images and the license page
(`LICENSE.rtf`, from the repository's `LICENSE`) into `packages/cli/installer/`. Needs only pillow:

    uv run python scripts/dev/brand/cli_installer.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


class CliInstallerAssets:
    """Generates the images and license page the Inno Setup script uses."""

    REPO_ROOT = Path(__file__).resolve().parents[3]
    ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    WIZARD_BACKGROUND = (255, 255, 255)
    BACKSLASH = chr(92)

    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        self.license = repo_root / "LICENSE"
        self.installer = repo_root / "packages" / "cli" / "installer"
        self.master = Image.open(repo_root / "icons" / "icon-512.png").convert("RGBA")

    def write_icon(self) -> None:
        self.master.save(self.installer / "vethuq.ico", format="ICO", sizes=self.ICO_SIZES)

    @classmethod
    def _on_background(cls, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        """The icon centred (fit) on the wizard's white page, as a flat RGB bitmap."""
        canvas = Image.new("RGB", size, cls.WIZARD_BACKGROUND)
        edge = min(size)
        icon = image.resize((edge, edge), Image.Resampling.LANCZOS)
        canvas.paste(icon, ((size[0] - edge) // 2, (size[1] - edge) // 2), icon)
        return canvas

    def write_wizard_images(self) -> None:
        # Inno scales these at higher DPI; the sidebar is 164x314, the header 55x55.
        self._on_background(self.master, (55, 55)).save(self.installer / "wizard_small.bmp")
        self._on_background(self.master, (164, 314)).save(self.installer / "wizard_large.bmp")

    @classmethod
    def _escape(cls, text: str) -> str:
        out = []
        for ch in text:
            if ch in (cls.BACKSLASH, "{", "}"):
                out.append(cls.BACKSLASH + ch)
            elif ord(ch) > 127:
                code = ord(ch)
                out.append(f"{cls.BACKSLASH}u{code if code < 32768 else code - 65536}?")
            else:
                out.append(ch)
        return "".join(out)

    def write_license(self) -> None:
        """The license text as RTF, which is what Inno's license page shows."""
        paragraphs = []
        for line in self.license.read_text("utf-8").splitlines():
            paragraphs.append(self._escape(line) + self.BACKSLASH + "par")
        bs = self.BACKSLASH
        header = "{" + bs + "rtf1" + bs + "ansi" + bs + "deff0{" + bs + "fonttbl{" + bs + "f0"
        header += bs + "fswiss Segoe UI;}}" + bs + "f0" + bs + "fs20"
        rtf = header + "\n" + "\n".join(paragraphs) + "\n}"
        (self.installer / "LICENSE.rtf").write_text(rtf, encoding="ascii")

    def run(self) -> None:
        self.installer.mkdir(parents=True, exist_ok=True)
        self.write_icon()
        self.write_wizard_images()
        self.write_license()


if __name__ == "__main__":
    CliInstallerAssets().run()
