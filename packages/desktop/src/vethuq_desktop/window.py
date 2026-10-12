"""Window controllers: the real pywebview window, and a stand-in for running without one."""

from __future__ import annotations

import threading
from typing import Any


class WebviewWindowController:
    """Controls the pywebview window and follows its maximised state."""

    def __init__(self) -> None:
        self._window: Any = None
        self._maximized = False

    def attach(self, window: Any) -> None:
        self._window = window
        window.events.maximized += self._on_maximized
        window.events.restored += self._on_restored

    def _on_maximized(self) -> None:
        self._maximized = True

    def _on_restored(self) -> None:
        self._maximized = False

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
        self._window.destroy()


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
