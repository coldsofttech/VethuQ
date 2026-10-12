"""Build the VethuQ command-line installers (PyInstaller, then Inno Setup or a .deb).

    python scripts/release/release.py --cli --version 1.2.0
    python scripts/release/release.py --interactive-cli --version 1.2.0
    python scripts/release/release.py --background-service --version 1.2.0
    python scripts/release/release.py --worker --version 1.2.0
    python scripts/release/release.py --desktop --version 1.2.0
    python scripts/release/release.py --add-on --name xls --version 0.1.0
    python scripts/release/release.py --bundle --name office --version 0.1.0
    python scripts/release/release.py --cli --interactive-cli --background-service --worker --dev

One PyInstaller build makes every program (the desktop application on Windows only):

  1. PyInstaller turns `installer/shared/vethuq.spec` into `build/cli/vethuq/`:
     `vethuq(.exe)` (the command line), `vethuqic(.exe)` (the shell), `vethuqbs(.exe)` (the
     background service), `vethuqw(.exe)` (the worker), `vethuqd.exe` (the desktop
     application: Windows only, built when `vethuq-desktop` is installed, with the React interface
     from `web/dist` inside `lib/`), `lib/` (the runtime and every dependency,
     plus `runtime-id.txt`) and `add-ons/` (the default add-ons). The `vethuq background`
     commands (add-ons/background) are moved to `build/cli/background-plugin/` for the service's
     installer.
  2. `--cli`: Windows: Inno Setup (`iscc`) wraps `vethuq`, `lib/` and `add-ons/` into
     `dist/VethuQ-CLI-Setup.exe`. Linux: `dpkg-deb` packs them into
     `dist/vethuq-cli_<version>_<arch>.deb` (installs to /opt/vethuq, /usr/bin/vethuq).
  3. `--interactive-cli`: only `vethuqic` is packed, for the same folder as the command line,
     whose `lib/` and `add-ons/` it reuses: `dist/VethuQ-Interactive-CLI-Setup.exe`, or
     `dist/vethuq-interactive-cli_<version>_<arch>.deb` (depends on vethuq-cli). Both refuse to
     install over a command line built from different libraries (`runtime-id.txt`).
  4. `--background-service`: only `vethuqbs` and the `vethuq background` commands are packed, again
     for the command line's folder: `dist/VethuQ-Background-Service-Setup.exe`, or
     `dist/vethuq-background-service_<version>_<arch>.deb` (depends on vethuq-cli).
  5. `--worker`: only `vethuqw` is packed, again for the command line's folder:
     `dist/VethuQ-Worker-Setup.exe`, or `dist/vethuq-worker_<version>_<arch>.deb` (depends on
     vethuq-cli; `/usr/bin/vethuq-worker` runs it).
  6. `--desktop`: only `vethuqd.exe` is packed, again for the command line's folder:
     `dist/VethuQ-Desktop-Setup.exe` (Windows 11 only: a WebView2 window, with a Start menu entry).
     The interface is built first (`npm ci && npm run build` in `web/`) when `web/dist` is missing.
  7. `--add-on --name NAME`: one add-on, no PyInstaller (compiled modules + a few packages).
     The wheel is built from the sibling VethuQ-premium checkout (`--premium PATH`) and installs
     into `<VethuQ>/add-ons/<name>/`; the packages it needs that VethuQ does not already carry go
     in the shared `<VethuQ>/lib/`, at the versions pinned in `installer/addon/constraints.txt`,
     and are removed with the last add-on that needs them. Inno Setup / `dpkg-deb` pack it into
     `dist/VethuQ-Addon-<name>-Setup.exe` or `dist/vethuq-addon-<name>_<version>_<arch>.deb`. It
     refuses to run unless VethuQ is installed.
  8. `--bundle --name NAME`: the same for a bundle: all its add-ons (less the ones VethuQ
     installs by default) and the bundle's own package in one installer,
     `dist/VethuQ-Bundle-<name>-Setup.exe` or
     `dist/vethuq-bundle-<name>_<version>_<arch>.deb`. An add-on shared with another installer is
     counted and removed with the last one that needs it.
     `--add-on-constraints` rewrites `installer/addon/constraints.txt` (with `--check`: fails when
     it is out of date).

`--version` is the release version (`1.2.0`, or `1.2.0-rc1` for a release candidate). `--dev` skips
compression and reuses a PyInstaller build whose inputs haven't changed. Run it in an environment
where `vethuq-cli`, its add-ons and `pyinstaller` are installed (see docs/releasing.md).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "packages" / "cli" / "installer"
SHARED = REPO_ROOT / "installer" / "shared"
IC_INSTALLER = REPO_ROOT / "packages" / "interactive-cli" / "installer"
BS_INSTALLER = REPO_ROOT / "packages" / "background" / "installer"
W_INSTALLER = REPO_ROOT / "packages" / "worker" / "installer"
D_INSTALLER = REPO_ROOT / "packages" / "desktop" / "installer"
WEB = REPO_ROOT / "web"
BUILD = REPO_ROOT / "build" / "cli"
DIST = REPO_ROOT / "dist"
APP = BUILD / "vethuq"
# The `vethuq background` commands, kept out of the command line's add-ons/.
PLUGIN = BUILD / "background-plugin"
UV = shutil.which("uv") or "uv"
ADDON_INSTALLER = REPO_ROOT / "installer" / "addon"
CONSTRAINTS = ADDON_INSTALLER / "constraints.txt"

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
        installer_files = [
            *INSTALLER.glob("*.py"),
            *IC_INSTALLER.glob("*.py"),
            *BS_INSTALLER.glob("*.py"),
            *W_INSTALLER.glob("*.py"),
            *D_INSTALLER.glob("*.py"),
            *SHARED.glob("*.py"),
            SHARED / "vethuq.spec",
        ]
        for path in sorted(installer_files):
            digest.update(path.read_bytes())
        for path in sorted((REPO_ROOT / "packages").glob("*/src/**/*.py")):
            digest.update(str(path).encode() + path.read_bytes())
        if (WEB / "dist").is_dir():
            for path in sorted((WEB / "dist").rglob("*")):
                if path.is_file():
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
                str(SHARED / "vethuq.spec"),
            ]
        )
        self.move_addons()
        BUILD.mkdir(parents=True, exist_ok=True)
        stamp.write_text(key)

    def runtime_id(self) -> str:
        """Names the libraries lib/ was built from: the dependency lock, Python and PyInstaller.

        The interactive shell is installed on top of the command line's lib/, so the two builds must
        agree on this."""
        import PyInstaller  # noqa: PLC0415 - only needed once a build exists

        digest = hashlib.sha256()
        digest.update((REPO_ROOT / "uv.lock").read_bytes())
        digest.update(f"py{sys.version_info.major}.{sys.version_info.minor}".encode())
        digest.update(f"pyinstaller{PyInstaller.__version__}".encode())
        return digest.hexdigest()[:16]

    def stamp_runtime(self) -> str:
        identifier = self.runtime_id()
        (APP / "lib" / "runtime-id.txt").write_text(identifier + "\n", encoding="ascii")
        return identifier

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
        # `vethuq background ...` is the background service's installer's, not the command line's.
        if PLUGIN.exists():
            shutil.rmtree(PLUGIN)
        shutil.move(str(target / "background"), str(PLUGIN))
        # Add-ons installed from a checkout carry their __pycache__; the installers don't need it.
        for folder in (target, PLUGIN):
            for cache in folder.rglob("__pycache__"):
                shutil.rmtree(cache)

    @staticmethod
    def build_web() -> None:
        """The React interface the desktop application shows: `web/dist`, built when missing."""
        if (WEB / "dist" / "index.html").is_file():
            return
        npm = shutil.which("npm")
        if npm is None:
            raise ReleaseError("web/dist is missing and npm was not found to build it.")
        run([npm, "ci"], cwd=WEB)
        run([npm, "run", "build"], cwd=WEB)
        if not (WEB / "dist" / "index.html").is_file():
            raise ReleaseError("The interface did not build: web/dist/index.html is missing.")

    def check_build(self, *, desktop: bool = False) -> None:
        """What the installers rely on is there."""
        suffix = ".exe" if os.name == "nt" else ""
        required = (
            APP / f"vethuq{suffix}",
            APP / f"vethuqic{suffix}",
            APP / f"vethuqbs{suffix}",
            APP / f"vethuqw{suffix}",
            APP / "lib",
            APP / "add-ons",
            PLUGIN,
        )
        if desktop:
            required = (*required, APP / "vethuqd.exe")
        missing = [p for p in required if not p.exists()]
        if missing:
            raise ReleaseError("The build is missing: " + ", ".join(str(p) for p in missing))
        if not any((APP / "add-ons").iterdir()):
            raise ReleaseError("build/cli/vethuq/add-ons is empty.")

    # ----- Windows: Inno Setup ----------------------------------------------------------------

    def inno(self, script: Path, output: str, *defines: str) -> Path:
        iscc = shutil.which("iscc") or shutil.which("ISCC")
        if iscc is None:
            raise ReleaseError("Inno Setup (iscc) was not found on PATH.")
        command = [
            iscc,
            f"/DMyAppVersion={self.version.display}",
            f"/DMyAppNumericVersion={self.version.numeric}",
            *defines,
        ]
        if self.dev:
            command.append("/DNoCompression")
        else:
            command.append(f"/DCompressThreads={min(os.cpu_count() or 1, 4)}")
        command.append(str(script))
        run(command)
        return DIST / output

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

    def control(
        self,
        arch: str,
        size_kb: int,
        package: str = "vethuq-cli",
        summary: str = "VethuQ command line",
        detail: str = " Document intelligence and evidence infrastructure: index, OCR and search\n"
        " documents from the terminal. Installs to /opt/vethuq with the default add-ons.\n",
        depends: str | None = None,
    ) -> str:
        libc = platform.libc_ver()[1]
        depends = depends or (f"libc6 (>= {libc})" if libc else "libc6")
        return (
            f"Package: {package}\n"
            f"Version: {self.version.debian}\n"
            "Section: utils\n"
            "Priority: optional\n"
            f"Architecture: {arch}\n"
            f"Depends: {depends}\n"
            f"Installed-Size: {size_kb}\n"
            f"Maintainer: {MAINTAINER}\n"
            f"Homepage: {HOMEPAGE}\n"
            f"Description: {summary}\n"
            f"{detail}"
        )

    @staticmethod
    def set_modes(root: Path) -> None:
        for path in [root, *root.rglob("*")]:
            if path.is_symlink():
                continue
            if path.is_dir() or os.access(path, os.X_OK):
                path.chmod(0o755)
            else:
                path.chmod(0o644)

    def pack(self, root: Path, name: str, arch: str) -> Path:
        self.set_modes(root)
        DIST.mkdir(exist_ok=True)
        target = DIST / f"{name}_{self.version.debian}_{arch}.deb"
        compression = ["-Zgzip", "-z1"] if self.dev else ["-Zxz", "-z6"]
        run(["dpkg-deb", "--root-owner-group", *compression, "--build", str(root), str(target)])
        return target

    @staticmethod
    def stage(name: str) -> Path:
        if shutil.which("dpkg-deb") is None:
            raise ReleaseError("dpkg-deb was not found (install dpkg).")
        root = BUILD / name
        if root.exists():
            shutil.rmtree(root)
        return root

    @staticmethod
    def changelog(doc: Path, package: str) -> None:
        doc.mkdir(parents=True)
        shutil.copy(REPO_ROOT / "LICENSE", doc / "copyright")
        changelog = REPO_ROOT / "packages" / package / "CHANGELOG.md"
        if changelog.is_file():
            with (doc / "changelog.gz").open("wb") as raw:
                with gzip.GzipFile("", "wb", 9, raw, mtime=0) as handle:
                    handle.write(changelog.read_bytes())

    # Add-ons put packages in lib/ and folders in add-ons/ that dpkg does not own: they go with
    # VethuQ.
    POSTRM = """#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
    rm -rf /opt/vethuq/lib /opt/vethuq/add-ons /opt/vethuq/.owners
    rmdir /opt/vethuq 2>/dev/null || true
fi
"""

    def deb(self) -> Path:
        arch = self.architecture()
        root = self.stage("deb")
        # The interactive shell is a package of its own.
        shutil.copytree(
            APP,
            root / "opt" / "vethuq",
            symlinks=True,
            ignore=shutil.ignore_patterns("vethuqic", "vethuqbs", "vethuqw"),
        )
        (root / "usr" / "bin").mkdir(parents=True)
        (root / "usr" / "bin" / "vethuq").symlink_to("/opt/vethuq/vethuq")
        self.changelog(root / "usr" / "share" / "doc" / "vethuq-cli", "cli")
        (root / "DEBIAN").mkdir()
        (root / "DEBIAN" / "postrm").write_text(self.POSTRM, encoding="utf-8")
        (root / "DEBIAN" / "postrm").chmod(0o755)
        (root / "DEBIAN" / "control").write_text(
            self.control(arch, self.installed_size_kb(root)), encoding="utf-8"
        )
        return self.pack(root, "vethuq-cli", arch)

    @staticmethod
    def postinst(package: str) -> str:
        """Refuse to install on a vethuq-cli built from different libraries."""
        return f"""#!/bin/sh
set -e
if [ "$1" = configure ]; then
    want="$(cat /usr/share/{package}/runtime-id)"
    have="$(cat /opt/vethuq/lib/runtime-id.txt 2>/dev/null || echo none)"
    if [ "$want" != "$have" ]; then
        echo "{package}: vethuq-cli was built from different libraries." >&2
        echo "Update vethuq-cli to the matching release first." >&2
        exit 1
    fi
fi
"""

    DESKTOP = """[Desktop Entry]
Type=Application
Name=VethuQ Interactive
Comment=Menus over the VethuQ commands
Exec=/opt/vethuq/vethuqic
Icon=vethuq
Terminal=true
Categories=Utility;ConsoleOnly;
"""

    def interactive_deb(self, runtime_id: str) -> Path:
        """Only `vethuqic`: it runs from the CLI's /opt/vethuq, on its lib/ and add-ons/."""
        arch = self.architecture()
        root = self.stage("deb-ic")
        (root / "opt" / "vethuq").mkdir(parents=True)
        shutil.copy2(APP / "vethuqic", root / "opt" / "vethuq" / "vethuqic")
        (root / "usr" / "bin").mkdir(parents=True)
        (root / "usr" / "bin" / "vethuqic").symlink_to("/opt/vethuq/vethuqic")
        applications = root / "usr" / "share" / "applications"
        applications.mkdir(parents=True)
        (applications / "vethuqic.desktop").write_text(self.DESKTOP, encoding="utf-8")
        for size in (16, 32, 64, 256, 512):
            icons = root / "usr" / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps"
            icons.mkdir(parents=True)
            shutil.copy(REPO_ROOT / "icons" / f"icon-{size}.png", icons / "vethuq.png")
        data = root / "usr" / "share" / "vethuq-interactive-cli"
        data.mkdir(parents=True)
        (data / "runtime-id").write_text(runtime_id + "\n", encoding="ascii")
        self.changelog(root / "usr" / "share" / "doc" / "vethuq-interactive-cli", "interactive-cli")
        debian = root / "DEBIAN"
        debian.mkdir()
        (debian / "postinst").write_text(self.postinst("vethuq-interactive-cli"), encoding="utf-8")
        (debian / "postinst").chmod(0o755)
        (debian / "control").write_text(
            self.control(
                arch,
                self.installed_size_kb(root),
                package="vethuq-interactive-cli",
                summary="VethuQ interactive shell",
                detail=" Arrow-key menus over the vethuq commands (run vethuqic). Installs into\n"
                " the folder of vethuq-cli and uses its libraries and add-ons.\n",
                depends="vethuq-cli",
            ),
            encoding="utf-8",
        )
        return self.pack(root, "vethuq-interactive-cli", arch)

    def background_deb(self, runtime_id: str) -> Path:
        """`vethuqbs` and the `vethuq background` commands, into the CLI's /opt/vethuq."""
        arch = self.architecture()
        root = self.stage("deb-bs")
        opt = root / "opt" / "vethuq"
        opt.mkdir(parents=True)
        shutil.copy2(APP / "vethuqbs", opt / "vethuqbs")
        shutil.copytree(PLUGIN, opt / "add-ons" / "background", symlinks=True)
        (root / "usr" / "bin").mkdir(parents=True)
        (root / "usr" / "bin" / "vethuqbs").symlink_to("/opt/vethuq/vethuqbs")
        data = root / "usr" / "share" / "vethuq-background-service"
        data.mkdir(parents=True)
        (data / "runtime-id").write_text(runtime_id + "\n", encoding="ascii")
        self.changelog(root / "usr" / "share" / "doc" / "vethuq-background-service", "background")
        debian = root / "DEBIAN"
        debian.mkdir()
        (debian / "postinst").write_text(
            self.postinst("vethuq-background-service"), encoding="utf-8"
        )
        (debian / "postinst").chmod(0o755)
        (debian / "control").write_text(
            self.control(
                arch,
                self.installed_size_kb(root),
                package="vethuq-background-service",
                summary="VethuQ background indexing service",
                detail=" Works the index queue in the background; vethuq background install sets\n"
                " it up as a systemd user unit. Installs into the folder of vethuq-cli.\n",
                depends="vethuq-cli",
            ),
            encoding="utf-8",
        )
        return self.pack(root, "vethuq-background-service", arch)

    def worker_deb(self, runtime_id: str) -> Path:
        """`vethuqw`, into the CLI's /opt/vethuq; `/usr/bin/vethuq-worker` is what runners call."""
        arch = self.architecture()
        root = self.stage("deb-w")
        opt = root / "opt" / "vethuq"
        opt.mkdir(parents=True)
        shutil.copy2(APP / "vethuqw", opt / "vethuqw")
        (root / "usr" / "bin").mkdir(parents=True)
        (root / "usr" / "bin" / "vethuq-worker").symlink_to("/opt/vethuq/vethuqw")
        data = root / "usr" / "share" / "vethuq-worker"
        data.mkdir(parents=True)
        (data / "runtime-id").write_text(runtime_id + "\n", encoding="ascii")
        self.changelog(root / "usr" / "share" / "doc" / "vethuq-worker", "worker")
        debian = root / "DEBIAN"
        debian.mkdir()
        (debian / "postinst").write_text(self.postinst("vethuq-worker"), encoding="utf-8")
        (debian / "postinst").chmod(0o755)
        (debian / "control").write_text(
            self.control(
                arch,
                self.installed_size_kb(root),
                package="vethuq-worker",
                summary="VethuQ worker",
                detail=" Reads a job's pages for a GitHub runner (vethuq-worker run --job-id ID\n"
                " --payload DIR --out DIR). Installs into the folder of vethuq-cli.\n",
                depends="vethuq-cli",
            ),
            encoding="utf-8",
        )
        return self.pack(root, "vethuq-worker", arch)

    # ----- all --------------------------------------------------------------------------------

    def build(
        self,
        *,
        cli: bool = False,
        interactive: bool = False,
        background: bool = False,
        worker: bool = False,
        desktop: bool = False,
    ) -> list[Path]:
        if sys.platform not in ("win32", "linux"):
            raise ReleaseError(f"This builds on Windows and Linux, not {sys.platform}.")
        if desktop and sys.platform != "win32":
            raise ReleaseError("The desktop application is for Windows (WebView2).")
        if sys.platform == "win32" and importlib.util.find_spec("vethuq_desktop") is not None:
            # The Windows build carries the desktop application (and so the interface) whichever
            # installer is asked for, so the command line's shared lib/ is the same in all of them.
            self.build_web()
        self.pyinstaller()
        runtime_id = self.stamp_runtime()
        self.check_build(desktop=desktop)
        DIST.mkdir(exist_ok=True)
        built = []
        if sys.platform == "win32":
            if cli:
                built.append(self.inno(INSTALLER / "vethuq-cli.iss", "VethuQ-CLI-Setup.exe"))
            if interactive:
                built.append(
                    self.inno(
                        IC_INSTALLER / "vethuqic.iss",
                        "VethuQ-Interactive-CLI-Setup.exe",
                        f"/DRuntimeId={runtime_id}",
                    )
                )
            if background:
                built.append(
                    self.inno(
                        BS_INSTALLER / "vethuqbs.iss",
                        "VethuQ-Background-Service-Setup.exe",
                        f"/DRuntimeId={runtime_id}",
                    )
                )
            if worker:
                built.append(
                    self.inno(
                        W_INSTALLER / "vethuqw.iss",
                        "VethuQ-Worker-Setup.exe",
                        f"/DRuntimeId={runtime_id}",
                    )
                )
            if desktop:
                built.append(
                    self.inno(
                        D_INSTALLER / "vethuqd.iss",
                        "VethuQ-Desktop-Setup.exe",
                        f"/DRuntimeId={runtime_id}",
                    )
                )
        else:
            if cli:
                built.append(self.deb())
            if interactive:
                built.append(self.interactive_deb(runtime_id))
            if background:
                built.append(self.background_deb(runtime_id))
            if worker:
                built.append(self.worker_deb(runtime_id))
        return built


def normalise(name: str) -> str:
    """A distribution name as pip compares it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def default_addons() -> list[str]:
    """The add-ons VethuQ installs by default (installer/shared/default-addons.txt). Add-on and
    bundle installers skip them: they are already there."""
    lines = (SHARED / "default-addons.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


class AddOn(Cli):
    """The installers of one add-on, built from its sources in the VethuQ-premium checkout."""

    KIND = "add-on"
    FOLDER = "add-ons"  # under packages/ in VethuQ-premium
    PREFIX = "vethuq-addon-"

    def __init__(
        self, name: str, version: Version, premium: Path, *, dev: bool = False, clean: bool = False
    ) -> None:
        super().__init__(version, dev=dev, clean=clean)
        self.name = name
        self.premium = Path(premium)
        self.work = BUILD.parent / "addon" / f"{self.KIND}-{name}"
        self.dist_name = f"{self.PREFIX}{name}"

    @property
    def guid(self) -> str:
        """The AppId: the same every time, and different for every add-on and bundle."""
        url = f"https://github.com/coldsofttech/VethuQ/{self.KIND}/{self.name}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, url)).upper()

    @property
    def title(self) -> str:
        return f"{self.KIND} {self.name}"

    @property
    def output_name(self) -> str:
        return f"VethuQ-{'Addon' if self.KIND == 'add-on' else 'Bundle'}-{self.name}-Setup"

    # ----- the sources and the wheel ------------------------------------------------------------

    def source_of(self, dist_name: str, folder: str) -> Path:
        """The folder of `dist_name`'s pyproject under `packages/<folder>/` in VethuQ-premium."""
        for pyproject in sorted((self.premium / "packages" / folder).rglob("pyproject.toml")):
            if "src" in pyproject.parts:
                continue
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
            if project.get("name") == dist_name:
                return pyproject.parent
        raise ReleaseError(
            f"No {self.KIND} {self.name!r} in {self.premium} (looked for {dist_name}). "
            "Check out VethuQ-premium next to VethuQ, or pass --premium."
        )

    def source(self) -> Path:
        return self.source_of(self.dist_name, self.FOLDER)

    def build_wheel(self, dist_name: str, source: Path) -> Path:
        out = self.work / "wheels" / dist_name
        if out.exists():
            shutil.rmtree(out)
        run([UV, "build", "--wheel", "--out-dir", str(out), str(source)])
        wheels = sorted(out.glob("*.whl"))
        if len(wheels) != 1:
            raise ReleaseError(f"Expected one wheel in {out}, found {len(wheels)}.")
        return wheels[0]

    def check_version(self, wheel: Path) -> None:
        """The wheel is the release the tag names: its own version is the version."""
        built = wheel.name.split("-")[1]
        if built != self.version.release + (self.version.pre or ""):
            raise ReleaseError(
                f"{wheel.name} is version {built}, not {self.version.display}: set the "
                f"{self.KIND}'s version in VethuQ-premium to the tag's before releasing."
            )

    def member_ids(self) -> list[str]:
        """The add-ons this installs: itself."""
        if self.name in default_addons():
            raise ReleaseError(f"{self.name} is installed with VethuQ already: nothing to install.")
        return [self.name]

    # ----- what VethuQ already carries --------------------------------------------------------

    @staticmethod
    def pins(text: str) -> dict[str, str]:
        """`name==version` lines (markers and comments dropped) as {normalised name: version}."""
        found = {}
        for line in text.splitlines():
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", line.strip())
            if match:
                found[normalise(match[1])] = match[2]
        return found

    @staticmethod
    def base_lines() -> list[str]:
        """The command line's own packages as `name==version [; marker]` lines, from `uv.lock`:
        `vethuq-cli` and, through `vethuq`, the default add-ons and what they need."""
        result = subprocess.run(  # noqa: S603, S607 - fixed argv
            [
                UV,
                "export",
                "--frozen",
                "--no-dev",
                "--no-hashes",
                "--no-emit-workspace",
                "--package",
                "vethuq-cli",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
        return [
            line.strip()
            for line in result.stdout.splitlines()
            if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*==", line.strip())
        ]

    def provided(self) -> dict[str, str]:
        """What VethuQ already carries. An add-on ships only the rest."""
        return self.pins("\n".join(self.base_lines()))

    @staticmethod
    def requirements(wheel: Path) -> list[str]:
        """The wheel's own requirements, less VethuQ's packages and optional extras."""
        with zipfile.ZipFile(wheel) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            metadata = archive.read(name).decode("utf-8")
        wanted = []
        for line in metadata.splitlines():
            if not line.startswith("Requires-Dist:"):
                continue
            requirement = line.split(":", 1)[1].strip()
            if "extra ==" in requirement or normalise(
                re.split(r"[\s;\[<>=!~(]", requirement)[0]
            ).startswith("vethuq"):
                continue
            wanted.append(requirement)
        return wanted

    # ----- staging ------------------------------------------------------------------------

    @staticmethod
    def addon_requirements(premium: Path) -> list[str]:
        """What every add-on needs besides VethuQ's own packages, without repeats."""
        found: set[str] = set()
        for pyproject in sorted((Path(premium) / "packages" / "add-ons").rglob("pyproject.toml")):
            if "src" in pyproject.parts:
                continue
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
            for requirement in project.get("dependencies", []):
                if not normalise(re.split(r"[\s;\[<>=!~(]", requirement)[0]).startswith("vethuq"):
                    found.add(requirement.strip())
        return sorted(found)

    CONSTRAINTS_HEADER = (
        "# Generated by: python scripts/release/release.py --add-on-constraints (do not edit).\n"
        "# One version of every package any add-on needs, resolved together with the command\n"
        "# line's own pins (uv.lock), so add-ons installed side by side share one copy in\n"
        "# <VethuQ>/lib.\n"
        "# CI fails when this is out of date.\n"
    )

    @classmethod
    def constraints_text(cls, premium: Path) -> str:
        """All add-ons' requirements resolved together (for every platform) with the base's pins."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "base.txt"
            wanted = Path(folder) / "all.in"
            base.write_text("\n".join(cls.base_lines()) + "\n", encoding="utf-8")
            wanted.write_text("\n".join(cls.addon_requirements(premium)) + "\n", encoding="utf-8")
            result = subprocess.run(  # noqa: S603 - fixed argv
                [UV, "pip", "compile", "-q", "--no-header", "--no-annotate", "--universal"]
                + ["-c", str(base), str(wanted)],
                capture_output=True,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            raise ReleaseError(
                "The add-ons' requirements cannot be resolved together:\n" + result.stderr.strip()
            )
        pins = sorted(line for line in result.stdout.splitlines() if "==" in line)
        return cls.CONSTRAINTS_HEADER + "\n".join(pins) + "\n"

    @classmethod
    def write_constraints(cls, premium: Path, *, check: bool = False) -> bool:
        """Rewrite `installer/addon/constraints.txt`; with `check`, say whether it is current."""
        text = cls.constraints_text(premium)
        current = CONSTRAINTS.read_text(encoding="utf-8") if CONSTRAINTS.is_file() else ""
        if check:
            return text == current
        CONSTRAINTS.write_text(text, encoding="utf-8")
        return True

    # ----- staging ------------------------------------------------------------------------

    @staticmethod
    def extract(wheel: Path, target: Path) -> None:
        target.mkdir(parents=True)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(target)  # noqa: S202 - our own wheel
        for cache in target.rglob("__pycache__"):
            shutil.rmtree(cache)
        if not list(target.glob("*.dist-info")):
            raise ReleaseError(f"The staged package has no dist-info: {target}")

    def extra_files(self, tree: Path, wheels: dict[str, Path], main: Path) -> None:
        """What a kind adds to the tree besides its add-ons (nothing for an add-on)."""

    def stage_tree(self, wheels: dict[str, Path], main: Path) -> Path:
        """A tree that mirrors VethuQ's folder: `add-ons/<name>/` for every add-on (its package
        and dist-info, which holds the entry point VethuQ finds it by), and `lib/` for the packages
        they need that VethuQ does not carry. Those are pinned by `constraints.txt` (so every add-on
        agrees on one version), shared by all the add-ons here, and installed without dependencies,
        so nothing VethuQ carries is repeated."""
        tree = self.work / "stage"
        if tree.exists():
            shutil.rmtree(tree)
        for member, wheel in wheels.items():
            self.extract(wheel, tree / "add-ons" / member)
        self.extra_files(tree, wheels, main)
        needed = sorted({r for wheel in wheels.values() for r in self.requirements(wheel)})
        if not needed:
            return tree
        if not CONSTRAINTS.is_file():
            raise ReleaseError("constraints.txt is missing: run --add-on-constraints.")
        provided = self.provided()
        wanted = self.work / "requirements.in"
        wanted.write_text("\n".join(needed) + "\n", encoding="utf-8")
        compiled = subprocess.run(  # noqa: S603 - fixed argv
            [UV, "pip", "compile", "--no-header", "--no-annotate", "-q", "-c", str(CONSTRAINTS)]
            + [str(wanted)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise ReleaseError(
                f"{self.dist_name} needs a package that constraints.txt does not allow: run "
                f"--add-on-constraints.\n{compiled.stderr.strip()}"
            )
        extra = {n: v for n, v in self.pins(compiled.stdout).items() if n not in provided}
        if not extra:
            return tree
        lines = [f"{n}=={v}" for n, v in sorted(extra.items())]
        (self.work / "requirements.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        lib = tree / "lib"
        run(
            [UV, "pip", "install", "--no-deps", "--target", str(lib)]
            + ["-r", str(self.work / "requirements.txt")]
        )
        for scripts in ("bin", "Scripts"):
            shutil.rmtree(lib / scripts, ignore_errors=True)
        for cache in lib.rglob("__pycache__"):
            shutil.rmtree(cache)
        return tree

    # ----- the installers -----------------------------------------------------------------

    def windows(self, tree: Path) -> Path:
        return self.inno(
            ADDON_INSTALLER / "vethuq-addon.iss",
            f"{self.output_name}.exe",
            f"/DPackageId={self.package_id}",
            f"/DPackageTitle={self.title}",
            f"/DPackageGuid={self.guid}",
            f"/DOutputName={self.output_name}",
            f"/DStageDir={tree}",
        )

    @property
    def package_id(self) -> str:
        return self.name if self.KIND == "add-on" else f"bundle-{self.name}"

    PREINST = """#!/bin/sh
set -e
if [ "$1" = install ] || [ "$1" = upgrade ]; then
    if [ ! -x /opt/vethuq/vethuq ]; then
        echo "VethuQ is not installed. Install vethuq-cli first, then install this package." >&2
        exit 1
    fi
fi
"""

    # The package carries its files under /usr/share/<package>/stage/{add-ons,lib}/ and postinst
    # moves each entry into /opt/vethuq, because dpkg cannot have two packages own one file and an
    # add-on can arrive alone, in a bundle, or in two. Each package leaves a marker
    # /opt/vethuq/.owners/<folder>/<entry>/<package>; prerm removes it, and the last one to go takes
    # the entry. An entry VethuQ itself put there has no owners and is never taken. Every path
    # starts with a literal absolute folder, so nothing can expand to `/`.
    POSTINST = """#!/bin/sh
set -e
if [ "$1" = configure ] && [ -d /usr/share/@PKG@/stage ]; then
    mkdir -p /opt/vethuq/add-ons /opt/vethuq/lib
    for kind in add-ons lib; do
        for path in /usr/share/@PKG@/stage/$kind/*; do
            [ -e "$path" ] || continue
            entry="$(basename "$path")"
            [ -n "$entry" ] || continue
            if [ -e "/opt/vethuq/$kind/$entry" ]; then
                # Already there. VethuQ's own (no owners) is left alone; ours alone is replaced
                # (an upgrade); shared with another package it stays as it is.
                if [ ! -d "/opt/vethuq/.owners/$kind/$entry" ]; then
                    rm -rf "/usr/share/@PKG@/stage/$kind/$entry"
                    continue
                fi
                others="$(ls -A "/opt/vethuq/.owners/$kind/$entry" | grep -vx -- '@PKG@' | wc -l)"
                if [ "$others" = 0 ]; then
                    rm -rf "/opt/vethuq/$kind/$entry"
                    mv "/usr/share/@PKG@/stage/$kind/$entry" "/opt/vethuq/$kind/$entry"
                else
                    rm -rf "/usr/share/@PKG@/stage/$kind/$entry"
                fi
            else
                mv "/usr/share/@PKG@/stage/$kind/$entry" "/opt/vethuq/$kind/$entry"
            fi
            mkdir -p "/opt/vethuq/.owners/$kind/$entry"
            : > "/opt/vethuq/.owners/$kind/$entry/@PKG@"
        done
    done
fi
"""

    PRERM = """#!/bin/sh
set -e
if [ "$1" = remove ]; then
    for kind in add-ons lib; do
        [ -d "/opt/vethuq/.owners/$kind" ] || continue
        for path in /opt/vethuq/.owners/$kind/*; do
            entry="$(basename "$path")"
            [ -n "$entry" ] || continue
            [ -e "/opt/vethuq/.owners/$kind/$entry/@PKG@" ] || continue
            rm -f "/opt/vethuq/.owners/$kind/$entry/@PKG@"
            # The last package that needs it: take the entry away.
            if rmdir "/opt/vethuq/.owners/$kind/$entry" 2>/dev/null; then
                rm -rf "/opt/vethuq/$kind/$entry"
            fi
        done
        rmdir "/opt/vethuq/.owners/$kind" 2>/dev/null || true
    done
    rmdir /opt/vethuq/.owners 2>/dev/null || true
fi
"""

    def linux(self, tree: Path) -> Path:
        arch = self.architecture()
        package = self.dist_name
        root = Cli.stage(f"deb-{self.KIND}-{self.name}")
        # Staged here, moved into place by postinst (so it exists once on disk).
        shutil.copytree(tree, root / "usr" / "share" / package / "stage", symlinks=True)
        self.changelog_for(root / "usr" / "share" / "doc" / package, package)
        debian = root / "DEBIAN"
        debian.mkdir()
        scripts = {
            "preinst": self.PREINST,
            "postinst": self.POSTINST.replace("@PKG@", package),
            "prerm": self.PRERM.replace("@PKG@", package),
        }
        for script, text in scripts.items():
            (debian / script).write_text(text, encoding="utf-8")
            (debian / script).chmod(0o755)
        control = self.control(
            arch,
            self.installed_size_kb(root),
            package=package,
            summary=f"VethuQ {self.title}",
            detail=f" The {self.name} {self.KIND} for VethuQ. Installs into /opt/vethuq.\n",
            depends="vethuq-cli",
        )
        # Pre-Depends: dpkg refuses to unpack before VethuQ (vethuq-cli) is installed.
        control = control.replace("Depends: ", "Pre-Depends: ", 1)
        (debian / "control").write_text(control, encoding="utf-8")
        return self.pack(root, package, arch)

    @staticmethod
    def changelog_for(doc: Path, package: str) -> None:
        doc.mkdir(parents=True)
        shutil.copy(REPO_ROOT / "LICENSE", doc / "copyright")

    def build_addon(self) -> list[Path]:
        if sys.platform not in ("win32", "linux"):
            raise ReleaseError(f"This builds on Windows and Linux, not {sys.platform}.")
        wheels = {
            member: self.build_wheel(
                f"vethuq-addon-{member}", self.source_of(f"vethuq-addon-{member}", "add-ons")
            )
            for member in self.member_ids()
        }
        main = self.main_wheel(wheels)
        self.check_version(main)
        tree = self.stage_tree(wheels, main)
        DIST.mkdir(exist_ok=True)
        return [self.windows(tree) if sys.platform == "win32" else self.linux(tree)]

    def main_wheel(self, wheels: dict[str, Path]) -> Path:
        """The wheel whose version is the release's: the add-on's own."""
        return wheels[self.name]


class Bundle(AddOn):
    """The installers of one bundle: its members (less the ones VethuQ installs by default) in one
    installer, plus the bundle's own package so VethuQ lists it in `client.version.bundles`."""

    KIND = "bundle"
    FOLDER = "bundles"
    PREFIX = "vethuq-bundle-"

    def declared(self) -> list[str]:
        """The add-ons the bundle names, from its own pyproject (the one source of truth)."""
        pyproject = self.source() / "pyproject.toml"
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        names = []
        for requirement in project.get("dependencies", []):
            name = normalise(re.split(r"[\s;\[<>=!~(]", requirement)[0])
            if name.startswith("vethuq-addon-"):
                names.append(name.removeprefix("vethuq-addon-"))
        return names

    def member_ids(self) -> list[str]:
        defaults = default_addons()
        members = [name for name in self.declared() if name not in defaults]
        if not members:
            raise ReleaseError(f"Everything in the {self.name} bundle is installed with VethuQ.")
        return members

    def main_wheel(self, wheels: dict[str, Path]) -> Path:
        self._bundle_wheel = self.build_wheel(self.dist_name, self.source())
        return self._bundle_wheel

    def extra_files(self, tree: Path, wheels: dict[str, Path], main: Path) -> None:
        """The bundle's own package (add-ons/bundle-<name>/), and what is in it."""
        target = tree / "add-ons" / f"bundle-{self.name}"
        self.extract(main, target)
        versions = {m: wheel.name.split("-")[1] for m, wheel in wheels.items()}
        skipped = [n for n in self.declared() if n not in versions]
        (target / "bundle.json").write_text(
            json.dumps(
                {
                    "bundle": self.name,
                    "version": self.version.display,
                    "add-ons": versions,
                    "already installed with VethuQ": skipped,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cli", action="store_true", help="build the command-line installer")
    parser.add_argument(
        "--add-on",
        action="store_true",
        help="build the installer of one add-on (with --name); it installs into VethuQ's folder",
    )
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="build the installer of one bundle (with --name), e.g. --bundle --name office",
    )
    parser.add_argument("--name", help="the add-on or bundle to build, e.g. xls or office")
    parser.add_argument(
        "--add-on-constraints",
        action="store_true",
        help="rewrite installer/addon/constraints.txt from the add-ons in --premium",
    )
    parser.add_argument(
        "--check", action="store_true", help="with --add-on-constraints: only say if it is current"
    )
    parser.add_argument(
        "--premium",
        type=Path,
        default=Path(os.environ.get("VETHUQ_PREMIUM", REPO_ROOT.parent / "VethuQ-premium")),
        help="the VethuQ-premium checkout holding the add-on (default: next to this repository)",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help="build the worker's installer (it installs into the command line's folder)",
    )
    parser.add_argument(
        "--background-service",
        action="store_true",
        help="build the background service's installer (it installs into the CLI's folder)",
    )
    parser.add_argument(
        "--interactive-cli",
        action="store_true",
        help="build the interactive shell's installer (it installs into the command line's folder)",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="build the desktop application's installer (Windows; installs into the CLI's folder)",
    )
    parser.add_argument("--version", default="0.1.0", help="release version (X.Y.Z or X.Y.Z-rcN)")
    parser.add_argument("--dev", action="store_true", help="local iteration: quick, uncompressed")
    parser.add_argument("--clean", action="store_true", help="start from an empty build folder")
    args = parser.parse_args(argv)
    if args.add_on_constraints:
        try:
            current = AddOn.write_constraints(args.premium, check=args.check)
        except (ReleaseError, subprocess.CalledProcessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.check and not current:
            print(
                "error: installer/addon/constraints.txt is out of date: run "
                "scripts/release/release.py --add-on-constraints",
                file=sys.stderr,
            )
            return 1
        print("constraints.txt is current." if args.check else f"Wrote {CONSTRAINTS}")
        return 0
    if (args.add_on or args.bundle) and not args.name:
        parser.error("--add-on and --bundle need --name, e.g. --add-on --name xls")
    if args.add_on and args.bundle:
        parser.error("build an add-on or a bundle, not both")
    if args.add_on or args.bundle:
        kind = Bundle if args.bundle else AddOn
        try:
            built = kind(
                args.name, Version(args.version), args.premium, dev=args.dev, clean=args.clean
            ).build_addon()
        except (ReleaseError, subprocess.CalledProcessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for path in built:
            print(f"Built {path}")
        return 0
    if not (
        args.cli or args.interactive_cli or args.background_service or args.worker or args.desktop
    ):
        parser.error(
            "choose what to build: --cli, --interactive-cli, --background-service, --worker, "
            "--desktop, --add-on or --bundle"
        )
    try:
        built = Cli(Version(args.version), dev=args.dev, clean=args.clean).build(
            cli=args.cli,
            interactive=args.interactive_cli,
            background=args.background_service,
            worker=args.worker,
            desktop=args.desktop,
        )
    except (ReleaseError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in built:
        print(f"Built {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
