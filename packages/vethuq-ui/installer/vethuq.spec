# PyInstaller spec for VethuQ Desktop.
# Builds three executables - VethuQ-UI.exe (desktop, windowed), vethuq.exe
# (CLI) and vethuq-worker.exe (background index worker) - into ONE shared
# folder (build/desktop/VethuQ/), so the heavy OCR libraries exist once
# instead of once per exe. The folder is then compressed by Inno Setup
# (vethuq.iss), which can't shrink the already-compressed --onefile archives.
# Built by scripts/dev/release.py --desktop.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

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


ui_a = _analysis(
    UI_SRC / "app.py",
    datas=[(str(UI_SRC / "assets"), "vethuq_ui/assets"), *sv_ttk_datas],
    binaries=sv_ttk_binaries,
    hiddenimports=sv_ttk_hidden,
    excludes=OCR_MODULES,
)
cli_a = _analysis(
    CLI_SRC / "main.py",
    datas=rich_datas,
    binaries=rich_binaries,
    hiddenimports=rich_hidden,
    excludes=OCR_MODULES,
)
worker_a = _analysis(CORE_SRC / "index" / "runner.py")


def _exe(analysis, name, *, console):
    return EXE(
        PYZ(analysis.pure),
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
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
