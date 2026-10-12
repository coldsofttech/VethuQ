# PyInstaller spec for the VethuQ command line, its interactive shell and its background service
# (Windows and Linux).
#
# Three executables in one folder (build/cli/vethuq/), sharing one lib/ and one add-ons/:
#
#   vethuq(.exe)    the command line
#   vethuqic(.exe)  the interactive shell (arrow-key menus over the same commands)
#   vethuqbs(.exe)  the background service (works the index queue; a Windows service or systemd unit)
#   lib/            the Python runtime and every dependency (Paddle, rich, SQLAlchemy, ...)
#   add-ons/        the default add-ons, one folder each (pdf/, like/, ...); see addons_hook.py
#
# Each executable carries its own pure-Python modules; the native libraries and data files are
# collected once, in lib/. The CLI installer ships `vethuq`; the interactive shell's and the background
# service's installers ship `vethuqic` and `vethuqbs` into the same folder, on top of the CLI's lib/ and
# add-ons/. The `vethuq background ...` commands are the package `vethuq_background`, staged as
# add-ons/background (release.py moves it out to build/cli/background-plugin for the service's
# installer). No UI is built.
# PyInstaller puts data files in `lib/`; scripts/release/release.py moves `lib/add-ons` up beside
# the executables after the build.
# The entry scripts sit with their packages: packages/cli/installer/vethuq_entry.py and
# packages/interactive-cli/installer/vethuqic_entry.py and
# packages/background/installer/vethuqbs_entry.py.
# Built by `python scripts/release/release.py --cli`, `--interactive-cli` and `--background-service`.

import importlib.metadata as metadata
import importlib.util
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

# SPECPATH is installer/shared: this spec builds both programs, so it lives with what they share
# (the icon, images, license and the add-ons runtime hook).
SHARED = Path(SPECPATH)
REPO_ROOT = SHARED.parents[1]
INSTALLER = REPO_ROOT / "packages" / "cli" / "installer"
IC_INSTALLER = REPO_ROOT / "packages" / "interactive-cli" / "installer"
BS_INSTALLER = REPO_ROOT / "packages" / "background" / "installer"

# The add-ons VethuQ installs by default (its `dependencies` in packages/core/pyproject.toml).
# Everything else (lexical, proximity, fuzzy, noise-fuzzy, semantic, ...) is an extra.
DEFAULT_ADDONS = (
    "english",
    "pdf",
    "txt",
    "csv",
    "markdown",
    "paddle",
    "ocr-quick",
    "like",
    "exact",
    "full-text",
    "case",
    "unicode",
)

# Not part of the command line.
EXCLUDES = ["tkinter", "vethuq_ui", "pytest"]
# The command line has no shell in it: `vethuq --interactive` says to run `vethuqic`.
CLI_EXCLUDES = [*EXCLUDES, "vethuq_interactive_cli", "questionary", "prompt_toolkit"]

# Paddle's own packages are collected below with the handling they need.
PADDLE_PACKAGES = {"paddle", "paddlex", "paddleocr", "paddlepaddle"}


def _name(requirement):
    return re.split(r"[\s;\[<>=!~(]", requirement, maxsplit=1)[0]


def _normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _top_levels(dist_name):
    """The importable top-level packages of an installed distribution."""
    wanted = _normalise(dist_name)
    return sorted(
        top
        for top, dists in metadata.packages_distributions().items()
        if wanted in {_normalise(d) for d in dists}
    )


datas, binaries, hiddenimports = [], [], []


def _collect(package):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)


# ---- VethuQ itself: all in lib/ -------------------------------------------------------------
for dist in ("vethuq", "vethuq-cli", "vethuq-addon-api"):
    datas.extend(copy_metadata(dist))
hiddenimports.extend(collect_submodules("vethuq"))
hiddenimports.extend(collect_submodules("vethuq_cli"))
datas.extend(collect_data_files("vethuq"))  # the export templates and the palette
_collect("vethuq_addon_api")
# The compiled licensing runtime that the platform wheel of `vethuq` carries.
if importlib.util.find_spec("vethuq_entitlements") is not None:
    _collect("vethuq_entitlements")
# rich lazily imports a Unicode-version-specific submodule that static analysis can't see.
_collect("rich")
_collect("typer")

# ---- the default add-ons: add-ons/<id>/ --------------------------------------------------------
# Each add-on ships as its package and its dist-info (which holds the entry point VethuQ looks
# for). They are plain files, not frozen into the executable's archive.
third_party = set()
for addon in DEFAULT_ADDONS:
    dist_name = f"vethuq-addon-{addon}"
    dist = metadata.distribution(dist_name)
    for top in _top_levels(dist_name):
        # find_spec also finds an editable install's package, which isn't in site-packages.
        package_dir = importlib.util.find_spec(top).submodule_search_locations[0]
        datas.append((package_dir, f"add-ons/{addon}/{top}"))
    info = next(p for p in dist.files if ".dist-info/" in p.as_posix()).as_posix().split("/")[0]
    datas.append((str(dist.locate_file(info)), f"add-ons/{addon}/{info}"))
    for requirement in dist.requires or ():
        name = _normalise(_name(requirement))
        if name.startswith("vethuq") or "extra ==" in requirement:
            continue
        third_party.add(name)

# What the add-ons import (pypdfium2, snowballstemmer, markdown-it, ...) is frozen into lib/.
for dist_name in sorted(third_party):
    for top in _top_levels(dist_name):
        if top not in PADDLE_PACKAGES:
            _collect(top)
    datas.extend(copy_metadata(dist_name, recursive=True))

# ---- OCR: Paddle ------------------------------------------------------------------------------
# PaddleX finds its pipelines (OCR.yaml and friends) as data files beside the package and imports
# its pipeline and model classes by name, and PaddleOCR checks its dependencies through package
# metadata - none of which static analysis sees. Importing PaddleX to collect it would otherwise
# probe the network for model hosters. The models themselves are downloaded the first time OCR runs.
if "paddlepaddle" in third_party or "paddleocr" in third_party:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    for package in ("paddlex", "paddleocr"):
        _collect(package)
        datas.extend(copy_metadata(package, recursive=True))
    # Paddle loads several native libraries by name at run time (mklml, BLAS/LAPACK, the Fortran
    # runtime, ...) that PyInstaller's dependency scan misses: ship every file in its libs folder.
    _paddle = importlib.util.find_spec("paddle")
    _libs = Path(_paddle.submodule_search_locations[0]) / "libs"
    if _libs.is_dir():
        binaries.extend((str(f), "paddle/libs") for f in sorted(_libs.iterdir()) if f.is_file())
    # Creating the OCR pipeline checks that every package of PaddleX's `ocr-core` extra is
    # installed, by reading each one's package metadata.
    from paddlex.utils import deps as paddlex_deps

    for _dep in paddlex_deps.EXTRAS["ocr-core"]:
        datas.extend(copy_metadata(_dep))

# ---- the interactive shell: what only it needs ----------------------------------------------
ic_datas, ic_binaries, ic_hidden = [], [], []
for dist in ("vethuq-interactive-cli", "questionary", "prompt_toolkit", "wcwidth"):
    ic_datas.extend(copy_metadata(dist))
for package in ("vethuq_interactive_cli", "questionary", "prompt_toolkit", "wcwidth"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    ic_datas.extend(package_datas)
    ic_binaries.extend(package_binaries)
    ic_hidden.extend(package_hidden)


# ---- the background service -------------------------------------------------------------------
# `vethuqbs --service` hosts itself in the Windows service manager (pywin32), which static analysis
# can't see. The `vethuq background` commands are a plug-in of the command line: the package and its
# dist-info (with the `vethuq.cli` entry point) go to add-ons/background, where addons_hook.py puts
# them on sys.path, so `vethuq` and `vethuqic` find the commands once the service is installed.
bs_hidden = []
if sys.platform == "win32":
    bs_hidden = [
        "servicemanager",
        "win32service",
        "win32serviceutil",
        "win32event",
        "win32timezone",
        "win32api",
    ]
_bg_package = importlib.util.find_spec("vethuq_background").submodule_search_locations[0]
_bg_dist = metadata.distribution("vethuq-background")
_bg_info = next(p for p in _bg_dist.files if ".dist-info/" in p.as_posix()).as_posix().split("/")[0]
datas.append((_bg_package, "add-ons/background/vethuq_background"))
datas.append((str(_bg_dist.locate_file(_bg_info)), f"add-ons/background/{_bg_info}"))


def _exe_for(entry, name, extra_datas=(), extra_binaries=(), extra_hidden=(), excludes=()):
    analysis = Analysis(
        [str(entry)],
        pathex=[],
        binaries=[*binaries, *extra_binaries],
        datas=[*datas, *extra_datas],
        hiddenimports=[*hiddenimports, *extra_hidden],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[str(SHARED / "addons_hook.py")],
        excludes=list(excludes),
        noarchive=False,
    )
    exe = EXE(
        PYZ(analysis.pure),
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=True,
        icon=str(SHARED / "vethuq.ico") if os.name == "nt" else None,
        upx=False,
        # Everything but the executables goes in lib/ (COLLECT follows the EXE).
        contents_directory="lib",
    )
    return analysis, exe


cli_a, cli_exe = _exe_for(INSTALLER / "vethuq_entry.py", "vethuq", excludes=CLI_EXCLUDES)
ic_a, ic_exe = _exe_for(
    IC_INSTALLER / "vethuqic_entry.py",
    "vethuqic",
    extra_datas=ic_datas,
    extra_binaries=ic_binaries,
    extra_hidden=ic_hidden,
    excludes=EXCLUDES,
)
bs_a, bs_exe = _exe_for(
    BS_INSTALLER / "vethuqbs_entry.py",
    "vethuqbs",
    extra_hidden=bs_hidden,
    excludes=CLI_EXCLUDES,
)
coll = COLLECT(
    cli_exe,
    cli_a.binaries,
    cli_a.datas,
    ic_exe,
    ic_a.binaries,
    ic_a.datas,
    bs_exe,
    bs_a.binaries,
    bs_a.datas,
    name="vethuq",
    upx=False,
)
