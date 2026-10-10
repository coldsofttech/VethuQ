# PyInstaller spec for VethuQ Desktop.
# Builds three executables - VethuQ-UI.exe (desktop, windowed), vethuq.exe
# (CLI) and vethuq-worker.exe (background index worker, also the background service) - into ONE shared
# folder (build/desktop/VethuQ/), so the heavy OCR libraries exist once
# instead of once per exe. The folder is then compressed by Inno Setup
# (vethuq.iss), which can't shrink the already-compressed --onefile archives.
# Built by scripts/dev/release.py --desktop.

import importlib.util
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# SPECPATH is packages/vethuq-ui/installer
REPO_ROOT = Path(SPECPATH).parents[2]
UI_SRC = REPO_ROOT / "packages" / "vethuq-ui" / "src" / "vethuq_ui"
CLI_SRC = REPO_ROOT / "packages" / "vethuq-cli" / "src" / "vethuq_cli"
CORE_SRC = REPO_ROOT / "packages" / "vethuq-core" / "src" / "vethuq_core"

# The OCR stack is only needed by the worker. The UI and CLI just read
# results out of the database (vethuq_core.ocr imports these lazily, inside
# functions), so leaving them out of those two analyses keeps their
# embedded Python archives small. The shared folder still holds one copy of
# the native libraries, because the worker's analysis includes them.
OCR_MODULES = ["paddle", "paddleocr", "paddlex", "cv2", "pymupdf", "fitz"]

# Equivalent of the `--collect-all` flags the old per-exe builds used.
# sv_ttk ships theme files and rich lazily imports a Unicode-version-specific
# submodule (rich._unicode_data.unicodeNN_0_0) that static analysis can't see.
sv_ttk_datas, sv_ttk_binaries, sv_ttk_hidden = collect_all("sv_ttk")
rich_datas, rich_binaries, rich_hidden = collect_all("rich")


# PaddleX finds its pipelines (OCR.yaml and friends) as data files beside the package and imports
# its pipeline and model classes by name, and PaddleOCR checks its dependencies through package
# metadata - none of which static analysis sees. Only the worker runs OCR.
# Importing PaddleX to collect it would otherwise probe the network for model hosters.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
paddlex_datas, paddlex_binaries, paddlex_hidden = collect_all("paddlex")
paddleocr_datas, paddleocr_binaries, paddleocr_hidden = collect_all("paddleocr")
paddle_metadata = copy_metadata("paddlex", recursive=True) + copy_metadata(
    "paddleocr", recursive=True
)
# Paddle loads several native libraries by name at run time (mklml.dll, the BLAS/LAPACK and
# Fortran runtime DLLs, ...), which PyInstaller's dependency scan misses. Ship every file in its
# libs folder rather than trying to name the ones that are needed.
_paddle_libs = Path(importlib.util.find_spec("paddle").submodule_search_locations[0]) / "libs"
paddle_binaries = [(str(f), "paddle/libs") for f in sorted(_paddle_libs.iterdir()) if f.is_file()]

# Creating the OCR pipeline checks that every package of PaddleX's `ocr-core` extra (the one
# paddleocr depends on) is installed, by reading each one's package metadata.
from paddlex.utils import deps as paddlex_deps  # noqa: E402

for _dep in paddlex_deps.EXTRAS["ocr-core"]:
    paddle_metadata += copy_metadata(_dep)

# Semantic search runs its embedding model with ONNX Runtime and reads text with `tokenizers`
# (both native), and downloads the model with `huggingface_hub`. All three are imported lazily by
# `vethuq_core.semantic`, and ONNX Runtime and `tokenizers` load native libraries by name, so they
# are collected whole - for all three executables: the worker embeds the pages as they are indexed,
# the CLI and UI embed the query and any pages that are still missing. Only present when the
# `search-semantic` extra is installed in the build environment.
SEMANTIC_MODULES = ["onnxruntime", "tokenizers", "huggingface_hub"]
semantic_datas, semantic_binaries, semantic_hidden = [], [], []
for _module in SEMANTIC_MODULES:
    if importlib.util.find_spec(_module) is not None:
        _datas, _binaries, _hidden = collect_all(_module)
        semantic_datas += _datas
        semantic_binaries += _binaries
        semantic_hidden += _hidden
        try:
            semantic_datas += copy_metadata(_module.replace("_", "-"))
        except Exception:  # noqa: BLE001 - a build such as onnxruntime-gpu has another name
            pass

# File types are discovered at run time: FileTypes.all() lists the type.json manifests beside the
# package (so they must ship as files), and each type's reader is imported by name from the
# manifest (so static analysis can't see it).
FILETYPE_DATAS = [
    (str(manifest), f"vethuq_core/filetypes/{manifest.parent.name}")
    for manifest in sorted((CORE_SRC / "filetypes").glob("*/type.json"))
]
FILETYPE_HIDDEN = collect_submodules("vethuq_core.filetypes")

# Search engines are listed from the manifests beside the package (SearchEngineCatalog.all()),
# so those must ship as files too.
SEARCH_ENGINE_DATAS = [
    (str(manifest), "vethuq_core/search/engines/manifests")
    for manifest in sorted((CORE_SRC / "search" / "engines" / "manifests").glob("*.json"))
]


# OCR engines and languages are listed from their manifests beside the package
# (`OcrCatalog.engines()/languages()`), so those ship as files too. Each OCR language beyond English is
# a marker package (`vethuq_lang_te`) whose import is what `OcrCatalog` checks to see it is installed -
# nothing imports it by name, so it is a hidden import (the installer's language page decides which
# of the installed languages are enabled).
OCR_MANIFEST_DATAS = [
    (str(manifest), f"vethuq_core/ocr/{kind}/manifests")
    for kind in ("engines", "languages")
    for manifest in sorted((CORE_SRC / "ocr" / kind / "manifests").glob("*.json"))
]
LANGUAGE_HIDDEN = [
    f"vethuq_lang_{manifest.stem}"
    for manifest in sorted((CORE_SRC / "ocr" / "languages" / "manifests").glob("*.json"))
    if manifest.stem != "en" and importlib.util.find_spec(f"vethuq_lang_{manifest.stem}")
]


def _analysis(entry, *, datas=(), binaries=(), hiddenimports=(), excludes=()):
    return Analysis(
        [str(entry)],
        pathex=[],
        binaries=list(binaries),
        datas=list(datas),
        hiddenimports=list(hiddenimports),
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=list(excludes),
        noarchive=False,
    )


# The installer's version, written by scripts/dev/release.py just before this runs: the update check
# compares it with the policy's `desktop` entry. The UI and the CLI run the check; the worker never does.
_stamp = CORE_SRC / "updates" / "desktop_version.txt"
DESKTOP_VERSION_DATAS = [(str(_stamp), "vethuq_core/updates")] if _stamp.is_file() else []

ui_a = _analysis(
    UI_SRC / "app.py",
    datas=[
        # Not the whole assets folder: the Telugu fallback fonts in assets/fonts are put in
        # {app}\fonts by the installer, only when Telugu is chosen and Windows has no Telugu font.
        (str(UI_SRC / "assets" / "brand"), "vethuq_ui/assets/brand"),
        (str(UI_SRC / "assets" / "icons"), "vethuq_ui/assets/icons"),
        *sv_ttk_datas,
        *DESKTOP_VERSION_DATAS,
        *FILETYPE_DATAS,
        *SEARCH_ENGINE_DATAS,
        *OCR_MANIFEST_DATAS,
        *semantic_datas,
    ],
    binaries=[*sv_ttk_binaries, *semantic_binaries],
    hiddenimports=[*sv_ttk_hidden, *FILETYPE_HIDDEN, *LANGUAGE_HIDDEN, *semantic_hidden],
    excludes=OCR_MODULES,
)
cli_a = _analysis(
    CLI_SRC / "main.py",
    # The HTML export reads its templates from the package, so they must ship with the exe.
    datas=[
        (str(CORE_SRC / "search" / "templates"), "vethuq_core/search/templates"),
        # The CLI's styles are built from the palette at import time.
        (str(CORE_SRC / "branding" / "palette.json"), "vethuq_core/branding"),
        *rich_datas,
        *DESKTOP_VERSION_DATAS,
        *FILETYPE_DATAS,
        *SEARCH_ENGINE_DATAS,
        *OCR_MANIFEST_DATAS,
        *semantic_datas,
    ],
    binaries=[*rich_binaries, *semantic_binaries],
    hiddenimports=[*rich_hidden, *FILETYPE_HIDDEN, *LANGUAGE_HIDDEN, *semantic_hidden],
    excludes=OCR_MODULES,
)
worker_a = _analysis(
    CORE_SRC / "index" / "runner.py",
    datas=[
        *FILETYPE_DATAS,
        *SEARCH_ENGINE_DATAS,
        *OCR_MANIFEST_DATAS,
        *paddlex_datas,
        *paddleocr_datas,
        *paddle_metadata,
        *semantic_datas,
    ],
    binaries=[*paddle_binaries, *paddlex_binaries, *paddleocr_binaries, *semantic_binaries],
    hiddenimports=[
        *FILETYPE_HIDDEN,
        *LANGUAGE_HIDDEN,
        *paddlex_hidden,
        *paddleocr_hidden,
        *semantic_hidden,
        # The background service (--service) hosts itself in the Windows service manager.
        "servicemanager",
        "win32service",
        "win32serviceutil",
        "win32event",
        "win32timezone",
    ],
)


def _exe(analysis, name, *, console):
    return EXE(
        PYZ(analysis.pure),
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        icon=str(Path(SPECPATH) / "vethuq.ico"),
        console=console,
        upx=False,
        # Renames the onedir library folder each exe looks for its libs in
        # from PyInstaller's default "_internal" to something meaningful.
        # Set on every EXE (not just the one COLLECT reads it from) since
        # each exe's own bootloader also encodes this path independently.
        contents_directory="lib",
    )


ui_exe = _exe(ui_a, "VethuQ-UI", console=False)
# Console-subsystem so stderr reaches the worker log; IndexRunner.start_run
# hides the console window when it spawns the worker.
cli_exe = _exe(cli_a, "vethuq", console=True)
worker_exe = _exe(worker_a, "vethuq-worker", console=True)

COLLECT(
    ui_exe,
    ui_a.binaries,
    ui_a.datas,
    cli_exe,
    cli_a.binaries,
    cli_a.datas,
    worker_exe,
    worker_a.binaries,
    worker_a.datas,
    strip=False,
    upx=False,
    name="VethuQ",
)
