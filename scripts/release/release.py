"""Build the VethuQ command-line installers (PyInstaller, then Inno Setup or a .deb).

    python scripts/release/release.py --cli --version 1.2.0
    python scripts/release/release.py --interactive-cli --version 1.2.0
    python scripts/release/release.py --background-service --version 1.2.0
    python scripts/release/release.py --worker --version 1.2.0
    python scripts/release/release.py --add-on --name xls --version 0.1.0
    python scripts/release/release.py --cli --interactive-cli --background-service --worker --dev

No desktop app is built. One PyInstaller build makes both programs:

  1. PyInstaller turns `installer/shared/vethuq.spec` into `build/cli/vethuq/`:
     `vethuq(.exe)` (the command line), `vethuqic(.exe)` (the shell), `vethuqbs(.exe)` (the
     background service), `vethuqw(.exe)` (the worker), `lib/` (the runtime and every dependency,
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
  6. `--add-on --name NAME`: one add-on, no PyInstaller (compiled modules + a few packages).
     The wheel is built from the sibling VethuQ-premium checkout (`--premium PATH`); its
     dependencies that VethuQ does not already carry are staged beside it, and Inno Setup /
     `dpkg-deb` pack that
     into `dist/VethuQ-Addon-<name>-Setup.exe` or
     `dist/vethuq-addon-<name>_<version>_<arch>.deb`. It installs into
     `<VethuQ>/add-ons/<name>/` and refuses to run unless VethuQ is installed.

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
BUILD = REPO_ROOT / "build" / "cli"
DIST = REPO_ROOT / "dist"
APP = BUILD / "vethuq"
# The `vethuq background` commands, kept out of the command line's add-ons/.
PLUGIN = BUILD / "background-plugin"
UV = shutil.which("uv") or "uv"
ADDON_INSTALLER = REPO_ROOT / "installer" / "addon"

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
            *SHARED.glob("*.py"),
            SHARED / "vethuq.spec",
        ]
        for path in sorted(installer_files):
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

    def check_build(self) -> None:
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
    ) -> list[Path]:
        if sys.platform not in ("win32", "linux"):
            raise ReleaseError(f"This builds on Windows and Linux, not {sys.platform}.")
        self.pyinstaller()
        runtime_id = self.stamp_runtime()
        self.check_build()
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


class AddOn(Cli):
    """The installers of one add-on, built from its sources in the VethuQ-premium checkout."""

    def __init__(
        self, name: str, version: Version, premium: Path, *, dev: bool = False, clean: bool = False
    ) -> None:
        super().__init__(version, dev=dev, clean=clean)
        self.name = name
        self.premium = Path(premium)
        self.work = BUILD.parent / "addon" / name
        self.dist_name = f"vethuq-addon-{name}"

    @property
    def guid(self) -> str:
        """The add-on's AppId: the same every time, and different for every add-on."""
        url = f"https://github.com/coldsofttech/VethuQ/add-on/{self.name}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, url)).upper()

    # ----- the sources and the wheel ------------------------------------------------------------

    def source(self) -> Path:
        """The add-on's folder: `packages/add-ons/[group/[sub/]]<folder>` holds its pyproject."""
        for pyproject in sorted((self.premium / "packages" / "add-ons").rglob("pyproject.toml")):
            if "src" in pyproject.parts:
                continue
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
            if project.get("name") == self.dist_name:
                return pyproject.parent
        raise ReleaseError(
            f"No add-on {self.name!r} in {self.premium} (looked for {self.dist_name}). "
            "Check out VethuQ-premium next to VethuQ, or pass --premium."
        )

    def build_wheel(self) -> Path:
        out = self.work / "wheel"
        if out.exists():
            shutil.rmtree(out)
        run([UV, "build", "--wheel", "--out-dir", str(out), str(self.source())])
        wheels = sorted(out.glob("*.whl"))
        if len(wheels) != 1:
            raise ReleaseError(f"Expected one wheel in {out}, found {len(wheels)}.")
        return wheels[0]

    def check_version(self, wheel: Path) -> None:
        """The wheel is the release the tag names: the add-on's own version is the version."""
        built = wheel.name.split("-")[1]
        if built != self.version.release + (self.version.pre or ""):
            raise ReleaseError(
                f"{wheel.name} is version {built}, not {self.version.display}: set the add-on's "
                "version in VethuQ-premium to the tag's before releasing."
            )

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

    def provided(self) -> dict[str, str]:
        """The packages in the command line's build: `vethuq-cli` and, through `vethuq`, the default
        add-ons and what they need. An add-on is installed beside that, so it ships the
        rest."""
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
        return self.pins(result.stdout)

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

    def stage_files(self, wheel: Path) -> Path:
        """The folder that is installed: the add-on's package and dist-info, plus the packages it
        needs that VethuQ does not carry (pinned by `uv pip compile`, installed without dependencies
        so nothing VethuQ carries is repeated)."""
        folder = self.work / "stage"
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(folder)  # noqa: S202 - our own wheel
        needed = self.requirements(wheel)
        if needed:
            provided = self.provided()
            (self.work / "requirements.in").write_text("\n".join(needed) + "\n", encoding="utf-8")
            compiled = subprocess.run(  # noqa: S603, S607 - fixed argv
                [
                    UV,
                    "pip",
                    "compile",
                    "--no-header",
                    "--no-annotate",
                    "-q",
                    str(self.work / "requirements.in"),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            extra = {n: v for n, v in self.pins(compiled.stdout).items() if n not in provided}
            if extra:
                lines = [f"{n}=={v}" for n, v in sorted(extra.items())]
                (self.work / "requirements.txt").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
                run(
                    [
                        UV,
                        "pip",
                        "install",
                        "--no-deps",
                        "--target",
                        str(folder),
                        "-r",
                        str(self.work / "requirements.txt"),
                    ]
                )
        for scripts in ("bin", "Scripts"):
            shutil.rmtree(folder / scripts, ignore_errors=True)
        for cache in folder.rglob("__pycache__"):
            shutil.rmtree(cache)
        if not list(folder.glob("*.dist-info")):
            raise ReleaseError(f"The staged add-on has no dist-info: {folder}")
        return folder

    # ----- the installers -----------------------------------------------------------------

    def windows(self, folder: Path) -> Path:
        return self.inno(
            ADDON_INSTALLER / "vethuq-addon.iss",
            f"VethuQ-Addon-{self.name}-Setup.exe",
            f"/DAddonName={self.name}",
            f"/DAddonGuid={self.guid}",
            f"/DStageDir={folder}",
        )

    PREINST = """#!/bin/sh
set -e
if [ "$1" = install ] || [ "$1" = upgrade ]; then
    if [ ! -x /opt/vethuq/vethuq ]; then
        echo "VethuQ is not installed. Install vethuq-cli first, then install this add-on." >&2
        exit 1
    fi
fi
"""

    def linux(self, folder: Path) -> Path:
        arch = self.architecture()
        package = f"vethuq-addon-{self.name}"
        root = Cli.stage(f"deb-addon-{self.name}")
        shutil.copytree(folder, root / "opt" / "vethuq" / "add-ons" / self.name, symlinks=True)
        self.changelog_for(root / "usr" / "share" / "doc" / package, package)
        debian = root / "DEBIAN"
        debian.mkdir()
        (debian / "preinst").write_text(self.PREINST, encoding="utf-8")
        (debian / "preinst").chmod(0o755)
        control = self.control(
            arch,
            self.installed_size_kb(root),
            package=package,
            summary=f"VethuQ add-on {self.name}",
            detail=f" The {self.name} add-on for VethuQ. Installs into /opt/vethuq/add-ons.\n",
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
        wheel = self.build_wheel()
        self.check_version(wheel)
        folder = self.stage_files(wheel)
        DIST.mkdir(exist_ok=True)
        return [self.windows(folder) if sys.platform == "win32" else self.linux(folder)]


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
    parser.add_argument("--name", help="the add-on to build with --add-on, e.g. xls")
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
    parser.add_argument("--version", default="0.1.0", help="release version (X.Y.Z or X.Y.Z-rcN)")
    parser.add_argument("--dev", action="store_true", help="local iteration: quick, uncompressed")
    parser.add_argument("--clean", action="store_true", help="start from an empty build folder")
    args = parser.parse_args(argv)
    if args.add_on and not args.name:
        parser.error("--add-on needs --name, e.g. --add-on --name xls")
    if args.add_on:
        try:
            built = AddOn(
                args.name, Version(args.version), args.premium, dev=args.dev, clean=args.clean
            ).build_addon()
        except (ReleaseError, subprocess.CalledProcessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for path in built:
            print(f"Built {path}")
        return 0
    if not (args.cli or args.interactive_cli or args.background_service or args.worker):
        parser.error(
            "choose what to build: --cli, --interactive-cli, --background-service, --worker, "
            "--add-on"
        )
    try:
        built = Cli(Version(args.version), dev=args.dev, clean=args.clean).build(
            cli=args.cli,
            interactive=args.interactive_cli,
            background=args.background_service,
            worker=args.worker,
        )
    except (ReleaseError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in built:
        print(f"Built {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
