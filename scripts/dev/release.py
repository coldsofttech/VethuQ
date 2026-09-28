"""Build VethuQ's public release artifacts.

Both a developer and CI (`.github/workflows/release-check.yml`) run this,
and the publish workflows (`release.yml`, `release-desktop.yml`) run it
before creating a release, so a broken merge script or packaging config
fails on every PR, not on release day.

    uv run python scripts/dev/release.py --package
    uv run python scripts/dev/release.py --desktop   # Windows only

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
"""

from __future__ import annotations

import argparse
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


def build_package() -> None:
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


def build_desktop(*, version: str | None = None) -> None:
    if platform.system() != "Windows":
        print("desktop build is Windows-only - skipping on this platform.")
        return

    # `uv sync` alone only installs the workspace root's own deps, not
    # member packages like vethuq-ui/vethuq-cli - without this, PyInstaller's
    # `--collect-all sv_ttk` below silently collects nothing (sv_ttk isn't
    # installed anywhere) and produces an exe that fails at runtime with
    # ModuleNotFoundError.
    print("== syncing workspace packages for the desktop build ==")
    _run(["uv", "sync", "--all-packages", "--group", "desktop"])

    build_dir = REPO_ROOT / "build"
    dist_dir = build_dir / "desktop"

    # One spec builds all three exes (VethuQ-UI.exe, vethuq.exe,
    # vethuq-worker.exe) into a single shared folder, so the OCR libraries
    # aren't duplicated per exe - see packages/vethuq-ui/installer/vethuq.spec.
    spec_path = REPO_ROOT / "packages" / "vethuq-ui" / "installer" / "vethuq.spec"
    if not spec_path.exists():
        raise ReleaseBuildError(f"expected PyInstaller spec at {spec_path}")

    # PyInstaller's scratch output is intermediate and disposable - keep it
    # out of dist_dir and clean it up after a successful build.
    work_dir = build_dir / "_pyinstaller_work"
    print("== building VethuQ Desktop with PyInstaller ==")
    _run(
        [
            "uv",
            "run",
            "pyinstaller",
            "--noconfirm",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir),
            str(spec_path),
        ]
    )
    shutil.rmtree(work_dir, ignore_errors=True)

    app_dir = dist_dir / "VethuQ"
    for exe_name in ("VethuQ-UI.exe", "vethuq.exe", "vethuq-worker.exe"):
        if not (app_dir / exe_name).exists():
            raise ReleaseBuildError(f"expected PyInstaller output at {app_dir / exe_name}")
    print(f"built {app_dir}")

    iscc = shutil.which("iscc")
    if iscc is None:
        print("Inno Setup (iscc) not found on PATH - skipping installer wrap (CI has it).")
        return

    installer_script = REPO_ROOT / "packages" / "vethuq-ui" / "installer" / "vethuq.iss"
    if not installer_script.exists():
        raise ReleaseBuildError(f"expected Inno Setup script at {installer_script}")

    print("== wrapping with Inno Setup ==")
    iscc_cmd = [iscc]
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
            build_desktop(version=args.version)
    except (ReleaseBuildError, subprocess.CalledProcessError) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
