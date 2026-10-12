"""What the API needs from the host window (the desktop host provides it)."""

from __future__ import annotations

from typing import Protocol


class WindowController(Protocol):
    """Controls the application window. Implemented by the host that owns it."""

    @property
    def maximized(self) -> bool: ...

    def minimize(self) -> None: ...

    def maximize(self) -> None: ...

    def restore(self) -> None: ...

    def close(self) -> None: ...
