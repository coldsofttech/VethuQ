"""Real Windows shell icons for file-type badges in the search results list."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

try:
    import win32api
    import win32con
    import win32gui
    import win32ui
    from PIL import Image, ImageTk

    _SHELL_ICONS_AVAILABLE = True
except ImportError:
    _SHELL_ICONS_AVAILABLE = False

_icon_cache: dict[str, Any] = {}


def _shell_icon_for_suffix(suffix: str) -> Any | None:
    """Extract the OS-registered small icon for `suffix` (e.g. ".pdf")."""
    flags = win32con.SHGFI_ICON | win32con.SHGFI_SMALLICON | win32con.SHGFI_USEFILEATTRIBUTES
    _, _, _, _, icon_handle = win32gui.SHGetFileInfo(
        f"placeholder{suffix}", win32con.FILE_ATTRIBUTE_NORMAL, flags
    )
    if not icon_handle:
        return None

    width = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
    height = win32api.GetSystemMetrics(win32con.SM_CYSMICON)

    screen_dc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
    mem_dc = screen_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(screen_dc, width, height)
    mem_dc.SelectObject(bitmap)
    try:
        win32gui.DrawIconEx(
            mem_dc.GetHandleOutput(), 0, 0, icon_handle, width, height, 0, None, win32con.DI_NORMAL
        )
        bitmap_bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer("RGBA", (width, height), bitmap_bits, "raw", "BGRA", 0, 1)
        return ImageTk.PhotoImage(image)
    finally:
        win32gui.DestroyIcon(icon_handle)
        win32gui.DeleteObject(bitmap.GetHandle())
        mem_dc.DeleteDC()
        screen_dc.DeleteDC()


def get_file_icon(file_path: str | Path) -> Any:
    """Return the OS-registered icon for `file_path`'s extension, cached per extension.

    Falls back to a plain gray square when the Windows shell APIs aren't
    available (e.g. running on a non-Windows platform).
    """
    suffix = Path(file_path).suffix.lower() or ".file"
    if suffix in _icon_cache:
        return _icon_cache[suffix]

    icon: Any | None = None
    if _SHELL_ICONS_AVAILABLE:
        try:
            icon = _shell_icon_for_suffix(suffix)
        except Exception:
            icon = None
    if icon is None:
        icon = tk.PhotoImage(width=16, height=16)
        icon.put("#757575", to=(0, 0, 16, 16))

    _icon_cache[suffix] = icon
    return icon
