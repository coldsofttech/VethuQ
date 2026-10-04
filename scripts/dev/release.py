"""Build VethuQ's public release artifacts.

Both a developer and CI (`.github/workflows/release-check.yml`) run this,
and the publish workflows (`release.yml`, `release-desktop.yml`) run it
before creating a release, so a broken merge script or packaging config
fails on every PR, not on release day.

    uv run python scripts/dev/release.py --package
    uv run python scripts/dev/release.py --desktop   # Windows only

Both first regenerate the files derived from the file type and search engine manifests
(scripts/dev/sync_extras.py), so a stale extra or installer page can't ship.

`--package` (default if neither flag is given):
  1. Runs packages/vethuq/scripts/merge_sources.py.
  2. Builds the `vethuq` wheel+sdist (`uv build --package vethuq`) into
     `dist/` at the repo root.

`--desktop` (Windows only - no-ops elsewhere):
  1. Runs PyInstaller once, over vethuq-ui's entry point (VethuQ-UI.exe,
     windowed), vethuq-cli's entry point (vethuq.exe, console) and the
     background index worker (vethuq-worker.exe, console, spawned by the
     other two). All three land in one shared folder (build/desktop/VethuQ/).
  2. Wraps that folder with Inno Setup, if `iscc` is on PATH (warns and skips the
     installer step otherwise - a dev machine may not have Inno Setup
     installed; CI does). The installer optionally adds its install dir to
     PATH so `vethuq` works from any terminal. `--version` sets the version
     shown in the installer and in Windows' Apps & Features (defaults to
     vethuq.iss's own MyAppVersion fallback, "0.1.0", if omitted).

The installer is compressed with LZMA2 ultra64 (a few parallel blocks), except under `--dev`.

`--desktop --dev` is for local iteration and never used by CI: it skips `uv sync` and
PyInstaller when their inputs are unchanged since the last build, and builds the installer
without compression (quick, but as large as the app). `--clean` forces a full
PyInstaller rebuild (it also drops PyInstaller's analysis cache, which is otherwise kept
between builds); it is optional with `--dev` and always applied without it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class ReleaseBuildError(RuntimeError):
    """A release artifact failed to build."""


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, **kwargs)  # noqa: S603


class InstallerSizes:
    """Per-component install sizes, passed to Inno Setup for the Select Components page."""

    @staticmethod
    def _kb(*paths: Path) -> int:
        total = 0
        for path in paths:
            files = [path] if path.is_file() else [f for f in path.rglob("*") if f.is_file()]
            total += sum(f.stat().st_size for f in files)
        return (total + 1023) // 1024

    @staticmethod
    def defines(app_dir: Path) -> list[str]:
        """`/D` switches for iscc: the desktop app, the CLI, and the core runtime (worker + lib)."""
        return [
            f"/DAppSizeKB={InstallerSizes._kb(app_dir / 'VethuQ-UI.exe')}",
            f"/DCliSizeKB={InstallerSizes._kb(app_dir / 'vethuq.exe')}",
            f"/DCoreSizeKB={InstallerSizes._kb(app_dir / 'vethuq-worker.exe', app_dir / 'lib')}",
        ]


class ExtrasFiles:
    """The files generated from the file type and search engine manifests."""

    @staticmethod
    def regenerate() -> None:
        """Bring the extras and installer catalog in step with the manifests."""
        print("== regenerating extras and installer catalogs ==")
        _run([sys.executable, "scripts/dev/sync_extras.py"])


class DesktopCache:
    """Remembers what the last desktop build was made from, so `--dev` can skip unchanged steps."""

    STAMP_DIR = REPO_ROOT / "build" / ".stamps"

    @staticmethod
    def _files(patterns: list[str]) -> list[Path]:
        found = {
            path
            for pattern in patterns
            for path in REPO_ROOT.glob(pattern)
            if path.is_file() and "__pycache__" not in path.parts
        }
        return sorted(found)

    @staticmethod
    def fingerprint(patterns: list[str]) -> str:
        digest = hashlib.sha256()
        for path in DesktopCache._files(patterns):
            digest.update(path.relative_to(REPO_ROOT).as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def is_current(name: str, key: str) -> bool:
        stamp = DesktopCache.STAMP_DIR / name
        return stamp.exists() and stamp.read_text(encoding="utf-8") == key

    @staticmethod
    def record(name: str, key: str) -> None:
        DesktopCache.STAMP_DIR.mkdir(parents=True, exist_ok=True)
        (DesktopCache.STAMP_DIR / name).write_text(key, encoding="utf-8")

    @staticmethod
    def forget(name: str) -> None:
        (DesktopCache.STAMP_DIR / name).unlink(missing_ok=True)


def build_package() -> None:
    ExtrasFiles.regenerate()
    print("== merging vethuq-core + vethuq-cli into packages/vethuq ==")
    _run([sys.executable, "packages/vethuq/scripts/merge_sources.py"])

    print("== building vethuq wheel + sdist ==")
    dist_dir = REPO_ROOT / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    _run(["uv", "build", "--package", "vethuq"])

    wheels = sorted(dist_dir.glob("vethuq-*.whl"))
    if not wheels:
        raise ReleaseBuildError(f"no vethuq wheel found in {dist_dir}")
    print(f"built {wheels[-1]}")


def build_desktop(*, version: str | None = None, dev: bool = False, clean: bool = False) -> None:
    if platform.system() != "Windows":
        print("desktop build is Windows-only - skipping on this platform.")
        return
    # Only `--dev` may reuse earlier work; a normal build always starts from a clean PyInstaller
    # cache so a stale analysis can never leave a module out of the exe.
    clean = clean or not dev

    # `uv sync` alone only installs the workspace root's own deps, not
    # member packages like vethuq-ui/vethuq-cli - without this, PyInstaller's
    # `--collect-all sv_ttk` below silently collects nothing (sv_ttk isn't
    # installed anywhere) and produces an exe that fails at runtime with
    # ModuleNotFoundError.
    ExtrasFiles.regenerate()

    sync_key = DesktopCache.fingerprint(["uv.lock", "pyproject.toml", "packages/*/pyproject.toml"])
    if dev and not clean and DesktopCache.is_current("sync", sync_key):
        print("== workspace packages unchanged - skipping uv sync ==")
    else:
        print("== syncing workspace packages for the desktop build ==")
        DesktopCache.forget("sync")
        _run(["uv", "sync", "--all-packages", "--group", "desktop"])
        DesktopCache.record("sync", sync_key)

    build_dir = REPO_ROOT / "build"
    dist_dir = build_dir / "desktop"

    # One spec builds all three exes (VethuQ-UI.exe, vethuq.exe,
    # vethuq-worker.exe) into a single shared folder, so the OCR libraries
    # aren't duplicated per exe - see packages/vethuq-ui/installer/vethuq.spec.
    spec_path = REPO_ROOT / "packages" / "vethuq-ui" / "installer" / "vethuq.spec"
    if not spec_path.exists():
        raise ReleaseBuildError(f"expected PyInstaller spec at {spec_path}")

    # PyInstaller's work folder holds its analysis cache, so it is kept between builds to make
    # the next one faster under `--dev`; `--clean`, or any build without `--dev`, starts over.
    work_dir = build_dir / "_pyinstaller_work"
    app_dir = dist_dir / "VethuQ"
    exe_names = ("VethuQ-UI.exe", "vethuq.exe", "vethuq-worker.exe")
    build_key = DesktopCache.fingerprint(
        [
            "uv.lock",
            "packages/*/pyproject.toml",
            "packages/*/src/**/*",
            "packages/vethuq-ui/installer/vethuq.spec",
            "packages/vethuq-ui/installer/vethuq.ico",
        ]
    )
    if (
        dev
        and not clean
        and DesktopCache.is_current("pyinstaller", build_key)
        and all((app_dir / name).exists() for name in exe_names)
    ):
        print("== sources unchanged - skipping PyInstaller ==")
    else:
        DesktopCache.forget("pyinstaller")
        print("== building VethuQ Desktop with PyInstaller ==")
        command = ["uv", "run", "pyinstaller", "--noconfirm"]
        if clean:
            command.append("--clean")
        _run([*command, "--distpath", str(dist_dir), "--workpath", str(work_dir), str(spec_path)])
        for exe_name in exe_names:
            if not (app_dir / exe_name).exists():
                raise ReleaseBuildError(f"expected PyInstaller output at {app_dir / exe_name}")
        DesktopCache.record("pyinstaller", build_key)
    print(f"built {app_dir}")

    iscc = shutil.which("iscc")
    if iscc is None:
        print("Inno Setup (iscc) not found on PATH - skipping installer wrap (CI has it).")
        return

    installer_script = REPO_ROOT / "packages" / "vethuq-ui" / "installer" / "vethuq.iss"
    if not installer_script.exists():
        raise ReleaseBuildError(f"expected Inno Setup script at {installer_script}")

    print("== wrapping with Inno Setup ==")
    iscc_cmd = [iscc, *InstallerSizes.defines(app_dir)]
    if dev:
        iscc_cmd.append("/DNoCompression")
    else:
        iscc_cmd.append(f"/DCompressThreads={min(os.cpu_count() or 1, 4)}")
    if version is not None:
        iscc_cmd.append(f"/DMyAppVersion={version}")
    iscc_cmd.append(str(installer_script))
    _run(iscc_cmd)
    print(f"built {REPO_ROOT / 'dist' / 'VethuQ-Setup.exe'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--package", action="store_true", help="build the vethuq PyPI package (default)"
    )
    parser.add_argument(
        "--desktop", action="store_true", help="build the VethuQ Desktop installer (Windows only)"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="local iteration (--desktop only): skip unchanged steps, no compression",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "force a full PyInstaller rebuild, dropping its cache "
            "(--desktop only; always on without --dev)"
        ),
    )
    parser.add_argument(
        "--version",
        default=None,
        help="version to stamp the desktop installer with (--desktop only); "
        "e.g. the desktop-v* release tag with its prefix stripped",
    )
    args = parser.parse_args()

    if not args.package and not args.desktop:
        args.package = True

    try:
        if args.package:
            build_package()
        if args.desktop:
            build_desktop(version=args.version, dev=args.dev, clean=args.clean)
    except (ReleaseBuildError, subprocess.CalledProcessError) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
