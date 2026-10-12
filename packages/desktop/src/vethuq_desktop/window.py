"""Window controllers: the real pywebview window, and a stand-in for running without one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

from vethuq_desktop.opening import Opener


class WebviewWindowController:
    """Controls the pywebview window and follows its maximised state."""

    def __init__(self) -> None:
        self._window: Any = None
        self._maximized = False
        self._forced = False
        self._drop_ready = False
        # True while the application is running something that stops if it closes.
        self.close_guard: Callable[[], bool] | None = None

    def attach(self, window: Any) -> None:
        self._window = window
        window.events.maximized += self._on_maximized
        window.events.restored += self._on_restored
        window.events.closing += self._on_closing
        window.events.loaded += self._install_drop

    def _on_maximized(self) -> None:
        self._maximized = True

    def _on_restored(self) -> None:
        self._maximized = False

    def _on_closing(self) -> bool:
        """Closing the window by any means (Alt+F4, the taskbar). Held back, and the interface told
        to ask, while the application is running something that would stop."""
        if self._forced or self.close_guard is None or not self.close_guard():
            return True
        self.notify("vethuq:close-blocked")
        return False

    def notify(self, event: str, detail: object = None) -> None:
        """Tell the interface something happened in the host, as a DOM event on `window`."""
        init = json.dumps({"detail": detail})
        script = f"window.dispatchEvent(new CustomEvent({json.dumps(event)}, {init}))"
        try:
            self._window.evaluate_js(script)
        except Exception:  # noqa: BLE001 - the page may not be there (yet)
            return

    def _install_drop(self) -> None:
        """Files dropped on the window reach the interface with their full paths."""
        if self._drop_ready:
            return
        try:
            from webview.dom import DOMEventHandler

            events = self._window.dom.document.events
            events.dragover += DOMEventHandler(lambda _event: None, True, True)
            events.drop += DOMEventHandler(self._on_drop, True, True)
            self._drop_ready = True
        except Exception:  # noqa: BLE001 - an older pywebview; dropping files is a convenience
            return

    def _on_drop(self, event: dict[str, Any]) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        self.notify("vethuq:drop", {"paths": paths})

    @property
    def maximized(self) -> bool:
        return self._maximized

    def minimize(self) -> None:
        self._window.minimize()

    def maximize(self) -> None:
        self._window.maximize()
        self._maximized = True

    def restore(self) -> None:
        self._window.restore()
        self._maximized = False

    def close(self) -> None:
        self._forced = True
        self._window.destroy()

    def _dialog(self, kind: str, start: str | None, **options: Any) -> str | None:
        import webview

        dialog = getattr(webview, "FileDialog", None)
        value = getattr(dialog, kind, None)
        if value is None:  # older pywebview
            value = getattr(webview, f"{kind}_DIALOG")
        chosen = self._window.create_file_dialog(value, directory=start or "", **options)
        return str(chosen[0]) if chosen else None

    def choose_folder(self, start: str | None = None) -> str | None:
        """Show the system folder picker; the folder chosen, or None if it was cancelled."""
        return self._dialog("FOLDER", start)

    def choose_file(self, start: str | None = None) -> str | None:
        """Show the system file picker (one file); None if it was cancelled."""
        return self._dialog("OPEN", start, allow_multiple=False)

    def open_file(
        self,
        path: str,
        page: int | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> dict[str, object]:
        """Open a file in the application the system has for it, at the page or line if that
        application can be told. Says whether it jumped, and where to look if it did not."""
        return Opener().open(path, page, line, column).to_dict()

    def reveal(self, path: str) -> None:
        """Show a file or folder in the system file manager."""
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])  # noqa: S603, S607
        else:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(["xdg-open", folder])  # noqa: S603, S607


class SimulatedWindowController:
    """Keeps window state in memory so the title bar works in a browser (`--no-window`)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._maximized = False
        self.closed = threading.Event()

    @property
    def maximized(self) -> bool:
        return self._maximized

    def minimize(self) -> None:
        return None

    def maximize(self) -> None:
        with self._lock:
            self._maximized = True

    def restore(self) -> None:
        with self._lock:
            self._maximized = False

    def close(self) -> None:
        self.closed.set()
