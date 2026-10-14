"""Opening a file in the application the system has for it, at the place a search found.

Windows opens a file with whatever the person chose for its type, and each application takes its
own instructions to jump somewhere. This knows a few common ones: for a PDF the page (Edge, Chrome,
Firefox, Adobe Reader and Acrobat, SumatraPDF, Foxit), for a text, Markdown or CSV file the line
(Visual Studio Code, Notepad++, Sublime Text). For any other application the file is opened at the
top and the result says where to look, so the interface can tell the person.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

BROWSERS = ("msedge.exe", "chrome.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe")
ADOBE = ("acrord32.exe", "acrord64.exe", "acrobat.exe")
CODE_EDITORS = ("code.exe", "code - insiders.exe", "codium.exe", "cursor.exe")
LINE_EXTENSIONS = (".txt", ".md", ".markdown", ".csv", ".tsv")


@dataclass(frozen=True)
class OpenResult:
    """What opening did: it `opened` the file, `jumped` to the place asked for or not, and when it
    did not, `hint` says where to look."""

    opened: bool
    jumped: bool
    hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"opened": self.opened, "jumped": self.jumped, "hint": self.hint}


def windows_default_app(extension: str) -> Path | None:
    """The program Windows opens files with this extension in, or None."""
    if sys.platform != "win32":
        return None
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    ASSOCSTR_EXECUTABLE = 2
    buffer = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(len(buffer))
    found = ctypes.windll.shlwapi.AssocQueryStringW(  # type: ignore[attr-defined]
        0, ASSOCSTR_EXECUTABLE, extension, None, buffer, ctypes.byref(size)
    )
    return Path(buffer.value) if found == 0 and buffer.value else None


def _launch(arguments: Sequence[str]) -> None:
    subprocess.Popen(list(arguments))  # noqa: S603 - a program found by the system and our own arguments


def _plain(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(os.path.normpath(path))  # noqa: S606 - the caller has checked the path
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", path])  # noqa: S603, S607


class Opener:
    """Opens files. The pieces that touch the system can be replaced, to test the choices."""

    def __init__(
        self,
        default_app: Callable[[str], Path | None] = windows_default_app,
        launch: Callable[[Sequence[str]], None] = _launch,
        plain: Callable[[str], None] = _plain,
    ) -> None:
        self._default_app = default_app
        self._launch = launch
        self._plain = plain

    def command(
        self, path: str, page: int | None, line: int | None, column: int | None
    ) -> list[str] | None:
        """The command that opens `path` at the place, or None when the default application is not
        one this knows how to tell."""
        extension = Path(path).suffix.lower()
        app = self._default_app(extension)
        if app is None:
            return None
        name, exe = app.name.lower(), str(app)
        if extension == ".pdf" and page:
            if name in BROWSERS:
                return [exe, f"{Path(path).resolve().as_uri()}#page={page}"]
            if name in ADOBE or "foxit" in name:
                return [exe, "/A", f"page={page}", path]
            if name.startswith("sumatrapdf"):
                return [exe, "-page", str(page), path]
        if extension in LINE_EXTENSIONS and line:
            place = f"{line}:{column}" if column else f"{line}"
            if name in CODE_EDITORS:
                return [exe, "-g", f"{path}:{place}"]
            if name.startswith("notepad++"):
                return [exe, f"-n{line}", *([f"-c{column}"] if column else []), path]
            if name.startswith("sublime_text"):
                return [exe, f"{path}:{place}"]
        return None

    @staticmethod
    def hint(page: int | None, line: int | None, column: int | None, extension: str) -> str | None:
        if extension == ".pdf" and page:
            return f"Go to page {page}."
        if extension in LINE_EXTENSIONS and line:
            return f"Go to line {line}" + (f", column {column}." if column else ".")
        return None

    def open(
        self,
        path: str,
        page: int | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> OpenResult:
        """Open `path`, at the place if the application can be told, else at the top."""
        command = self.command(path, page, line, column)
        if command is not None:
            try:
                self._launch(command)
                return OpenResult(True, True)
            except OSError:
                pass  # the program could not start: the plain open below still may
        self._plain(path)
        return OpenResult(True, False, self.hint(page, line, column, Path(path).suffix.lower()))
