"""Build the VethuQ command-line installers (PyInstaller, then Inno Setup or a .deb).

    python scripts/release/release.py --cli --version 1.2.0
    python scripts/release/release.py --cli --dev            # local iteration

`--cli` builds the command line only (no desktop app, no interactive shell):

  1. PyInstaller turns `packages/cli/installer/vethuq-cli.spec` into `build/cli/vethuq/`:
     `vethuq(.exe)`, `lib/` (the runtime and every dependency) and `add-ons/` (the default add-ons).
  2. Windows: Inno Setup (`iscc`) wraps that folder into `dist/VethuQ-CLI-Setup.exe`.
     Linux: `dpkg-deb` packs it into `dist/vethuq-cli_<version>_<arch>.deb` (installs to
     /opt/vethuq, with /usr/bin/vethuq pointing at it).

`--version` is the release version (`1.2.0`, or `1.2.0-rc1` for a release candidate). `--dev` skips
compression and reuses a PyInstaller build whose inputs haven't changed. Run it in an environment
where `vethuq-cli`, its add-ons and `pyinstaller` are installed (see docs/releasing.md).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "packages" / "cli" / "installer"
BUILD = REPO_ROOT / "build" / "cli"
DIST = REPO_ROOT / "dist"
APP = BUILD / "vethuq"

VERSION = re.compile(r"^(?P<release>\d+\.\d+\.\d+)(?:-?(?P<pre>rc\d+))?$")
MAINTAINER = "coldsofttech <noreply@github.com>"
HOMEPAGE = "https://github.com/coldsofttech/VethuQ"


class ReleaseError(Exception):
    """The build cannot go on."""


class Version:
    """A release version in the forms each tool wants."""

    def __init__(self, text: str) -> None:
        match = VERSION.match(text.strip())
        if match is None:
            raise ReleaseError(f"{text!r} is not a version. Use X.Y.Z or X.Y.Z-rcN.")
        self.release = match["release"]
        self.pre = match["pre"]

    @property
    def display(self) -> str:
        """What the installer shows: 1.2.0 or 1.2.0-rc1."""
        return self.release + (f"-{self.pre}" if self.pre else "")

    @property
    def numeric(self) -> str:
        """a.b.c.d for a Windows file version."""
        return f"{self.release}.0"

    @property
    def debian(self) -> str:
        """A release candidate sorts before the release it leads to: 1.2.0~rc1 < 1.2.0."""
        return self.release + (f"~{self.pre}" if self.pre else "")


def run(command: list[str], **kwargs) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True, **kwargs)  # noqa: S603


class Cli:
    """Builds the command-line installer for the platform this runs on."""

    def __init__(self, version: Version, *, dev: bool = False, clean: bool = False) -> None:
        self.version = version
        self.dev = dev
        self.clean = clean

    # ----- PyInstaller --------------------------------------------------------------------

    def _inputs_key(self) -> str:
        """A fingerprint of what the build is made from, so `--dev` can skip an unchanged build."""
        digest = hashlib.sha256()
        for path in sorted(INSTALLER.glob("*.py")) + [INSTALLER / "vethuq-cli.spec"]:
            digest.update(path.read_bytes())
        for path in sorted((REPO_ROOT / "packages").glob("*/src/**/*.py")):
            digest.update(str(path).encode() + path.read_bytes())
        return digest.hexdigest()

    def pyinstaller(self) -> None:
        stamp = BUILD / ".pyinstaller-key"
        key = self._inputs_key()
        if self.clean and BUILD.exists():
            shutil.rmtree(BUILD)
        if self.dev and stamp.is_file() and stamp.read_text() == key and APP.is_dir():
            print("PyInstaller inputs are unchanged - reusing build/cli/vethuq.")
            return
        if shutil.which("pyinstaller") is None and shutil.which("uv") is None:
            raise ReleaseError("PyInstaller is not installed (uv pip install pyinstaller).")
        if APP.exists():
            shutil.rmtree(APP)
        command = ["pyinstaller"] if shutil.which("pyinstaller") else ["uv", "run", "pyinstaller"]
        run(
            [
                *command,
                "--noconfirm",
                "--distpath",
                str(BUILD),
                "--workpath",
                str(BUILD / "_work"),
                str(INSTALLER / "vethuq-cli.spec"),
            ]
        )
        self.move_addons()
        BUILD.mkdir(parents=True, exist_ok=True)
        stamp.write_text(key)

    @staticmethod
    def move_addons() -> None:
        """PyInstaller puts data in lib/; the add-ons belong beside the executable."""
        inside = APP / "lib" / "add-ons"
        if not inside.is_dir():
            raise ReleaseError("The build has no add-ons: is vethuq installed with its add-ons?")
        target = APP / "add-ons"
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(inside), str(target))

    def check_build(self) -> None:
        """What the installers rely on is there."""
        exe = APP / ("vethuq.exe" if os.name == "nt" else "vethuq")
        missing = [p for p in (exe, APP / "lib", APP / "add-ons") if not p.exists()]
        if missing:
            raise ReleaseError("The build is missing: " + ", ".join(str(p) for p in missing))
        if not any((APP / "add-ons").iterdir()):
            raise ReleaseError("build/cli/vethuq/add-ons is empty.")

    # ----- Windows: Inno Setup ----------------------------------------------------------------

    def inno(self) -> Path:
        iscc = shutil.which("iscc") or shutil.which("ISCC")
        if iscc is None:
            raise ReleaseError("Inno Setup (iscc) was not found on PATH.")
        command = [
            iscc,
            f"/DMyAppVersion={self.version.display}",
            f"/DMyAppNumericVersion={self.version.numeric}",
        ]
        if self.dev:
            command.append("/DNoCompression")
        else:
            command.append(f"/DCompressThreads={min(os.cpu_count() or 1, 4)}")
        command.append(str(INSTALLER / "vethuq-cli.iss"))
        run(command)
        return DIST / "VethuQ-CLI-Setup.exe"

    # ----- Linux: .deb ------------------------------------------------------------------------

    ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

    def architecture(self) -> str:
        machine = platform.machine().lower()
        if machine not in self.ARCHITECTURES:
            raise ReleaseError(f"No .deb architecture for {machine!r}.")
        return self.ARCHITECTURES[machine]

    @staticmethod
    def installed_size_kb(folder: Path) -> int:
        total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        return (total + 1023) // 1024

    def control(self, arch: str, size_kb: int) -> str:
        libc = platform.libc_ver()[1]
        depends = f"libc6 (>= {libc})" if libc else "libc6"
        return (
            "Package: vethuq-cli\n"
            f"Version: {self.version.debian}\n"
            "Section: utils\n"
            "Priority: optional\n"
            f"Architecture: {arch}\n"
            f"Depends: {depends}\n"
            f"Installed-Size: {size_kb}\n"
            f"Maintainer: {MAINTAINER}\n"
            f"Homepage: {HOMEPAGE}\n"
            "Description: VethuQ command line\n"
            " Document intelligence and evidence infrastructure: index, OCR and search\n"
            " documents from the terminal. Installs to /opt/vethuq with the default add-ons.\n"
        )

    def deb(self) -> Path:
        if shutil.which("dpkg-deb") is None:
            raise ReleaseError("dpkg-deb was not found (install dpkg).")
        arch = self.architecture()
        root = BUILD / "deb"
        if root.exists():
            shutil.rmtree(root)
        opt = root / "opt" / "vethuq"
        shutil.copytree(APP, opt, symlinks=True)
        (root / "usr" / "bin").mkdir(parents=True)
        (root / "usr" / "bin" / "vethuq").symlink_to("/opt/vethuq/vethuq")
        doc = root / "usr" / "share" / "doc" / "vethuq-cli"
        doc.mkdir(parents=True)
        shutil.copy(REPO_ROOT / "LICENSE", doc / "copyright")
        changelog = REPO_ROOT / "packages" / "cli" / "CHANGELOG.md"
        if changelog.is_file():
            with gzip.open(doc / "changelog.gz", "wb", compresslevel=9, mtime=0) as handle:
                handle.write(changelog.read_bytes())
        debian = root / "DEBIAN"
        debian.mkdir()
        (debian / "control").write_text(
            self.control(arch, self.installed_size_kb(root)), encoding="utf-8"
        )
        for path in [root, *root.rglob("*")]:
            if path.is_symlink():
                continue
            if path.is_dir():
                path.chmod(0o755)
            elif os.access(path, os.X_OK):
                path.chmod(0o755)
            else:
                path.chmod(0o644)
        DIST.mkdir(exist_ok=True)
        target = DIST / f"vethuq-cli_{self.version.debian}_{arch}.deb"
        compression = ["-Zgzip", "-z1"] if self.dev else ["-Zxz", "-z6"]
        run(["dpkg-deb", "--root-owner-group", *compression, "--build", str(root), str(target)])
        return target

    # ----- all --------------------------------------------------------------------------------

    def build(self) -> Path:
        if sys.platform not in ("win32", "linux"):
            raise ReleaseError(f"--cli builds on Windows and Linux, not {sys.platform}.")
        self.pyinstaller()
        self.check_build()
        DIST.mkdir(exist_ok=True)
        return self.inno() if sys.platform == "win32" else self.deb()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cli", action="store_true", help="build the command-line installer")
    parser.add_argument("--version", default="0.1.0", help="release version (X.Y.Z or X.Y.Z-rcN)")
    parser.add_argument("--dev", action="store_true", help="local iteration: quick, uncompressed")
    parser.add_argument("--clean", action="store_true", help="start from an empty build folder")
    args = parser.parse_args(argv)
    if not args.cli:
        parser.error("choose what to build: --cli")
    try:
        result = Cli(Version(args.version), dev=args.dev, clean=args.clean).build()
    except (ReleaseError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Built {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
