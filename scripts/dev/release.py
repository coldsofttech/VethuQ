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
  1. Runs PyInstaller over vethuq-ui's entry point (VethuQ.exe, windowed)
     and vethuq-cli's entry point (vethuq.exe, console).
  2. Wraps both with Inno Setup, if `iscc` is on PATH (warns and skips the
     installer step otherwise - a dev machine may not have Inno Setup
     installed; CI does). The installer optionally adds its install dir to
     PATH so `vethuq` works from any terminal.
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


def _build_exe(
    *,
    name: str,
    entry: Path,
    dist_dir: Path,
    build_dir: Path,
    windowed: bool,
    extra_args: list[str] | None = None,
) -> Path:
    # PyInstaller's own scratch output (--workpath, the .spec file) is
    # intermediate and disposable - keep it out of dist_dir and clean it
    # up after a successful build, so only the exe is left behind. Each
    # build gets its own work/spec dirs so the two PyInstaller runs (UI,
    # CLI) don't clobber each other.
    work_dir = build_dir / f"_pyinstaller_work_{name}"
    spec_dir = build_dir / f"_pyinstaller_spec_{name}"
    cmd = [
        "uv",
        "run",
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
    ]
    if windowed:
        cmd.append("--windowed")
    cmd.extend(extra_args or [])
    cmd.append(str(entry))
    _run(cmd)
    shutil.rmtree(work_dir, ignore_errors=True)
    shutil.rmtree(spec_dir, ignore_errors=True)

    exe_path = dist_dir / f"{name}.exe"
    if not exe_path.exists():
        raise ReleaseBuildError(f"expected PyInstaller output at {exe_path}")
    print(f"built {exe_path}")
    return exe_path


def build_desktop() -> None:
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

    print("== building vethuq-ui with PyInstaller ==")
    ui_src = REPO_ROOT / "packages" / "vethuq-ui" / "src" / "vethuq_ui"
    _build_exe(
        name="VethuQ",
        entry=ui_src / "app.py",
        dist_dir=dist_dir,
        build_dir=build_dir,
        windowed=True,
        extra_args=[
            "--add-data",
            f"{ui_src / 'assets'};vethuq_ui/assets",
            "--collect-all",
            "sv_ttk",
        ],
    )

    print("== building vethuq-cli with PyInstaller ==")
    cli_src = REPO_ROOT / "packages" / "vethuq-cli" / "src" / "vethuq_cli"
    _build_exe(
        name="vethuq",
        entry=cli_src / "main.py",
        dist_dir=dist_dir,
        build_dir=build_dir,
        windowed=False,
        # rich lazily imports a Unicode-version-specific submodule
        # (rich._unicode_data.unicodeNN_0_0) that PyInstaller's static
        # analysis can't see, so it's missing from the bundle without this
        # - same class of issue as --collect-all sv_ttk above.
        extra_args=["--collect-all", "rich"],
    )

    iscc = shutil.which("iscc")
    if iscc is None:
        print("Inno Setup (iscc) not found on PATH - skipping installer wrap (CI has it).")
        return

    installer_script = REPO_ROOT / "packages" / "vethuq-ui" / "installer" / "vethuq.iss"
    if not installer_script.exists():
        raise ReleaseBuildError(f"expected Inno Setup script at {installer_script}")

    print("== wrapping with Inno Setup ==")
    _run([iscc, str(installer_script)])
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
    args = parser.parse_args()

    if not args.package and not args.desktop:
        args.package = True

    try:
        if args.package:
            build_package()
        if args.desktop:
            build_desktop()
    except (ReleaseBuildError, subprocess.CalledProcessError) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
