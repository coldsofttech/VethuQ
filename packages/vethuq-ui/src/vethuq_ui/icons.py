"""File-type badge and ribbon action icons.

Both kinds load from the checked-in assets under `assets/icons/`
(generated via the vethuq-icons skill - see `.claude/skills/vethuq-icons/`):

- `get_file_icon` - file-type badges for the search results list. Any
  extension without a generated asset yet falls back to the real Windows
  shell icon, then to a plain gray square as a last resort.
- `get_icon` - ribbon action icons (Search, Sources, GPU, ...), looked up
  by logical name rather than file suffix. Returns None for a name with no
  asset yet, so callers can fall back to a text-only control.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from PIL import Image, ImageTk

try:
    import win32api
    import win32con
    import win32gui
    import win32ui

    _SHELL_ICONS_AVAILABLE = True
except ImportError:
    _SHELL_ICONS_AVAILABLE = False

_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "icons"
_ICON_SIZE = 16
_RIBBON_ICON_SIZE = 32

# .jpeg has no asset of its own - it's the same format as .jpg.
_SUFFIX_ASSET_ALIASES = {".jpeg": "jpg"}

_icon_cache: dict[str, Any] = {}


def _load_asset(asset_path: Path, size: int) -> Any | None:
    if not asset_path.is_file():
        return None
    image = Image.open(asset_path).convert("RGBA")
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(image)


def _static_asset_icon(suffix: str) -> Any | None:
    """Load a checked-in icon asset for `suffix` (e.g. ".pdf" -> assets/icons/pdf.png)."""
    stem = _SUFFIX_ASSET_ALIASES.get(suffix, suffix.lstrip("."))
    return _load_asset(_ASSETS_DIR / f"{stem}.png", _ICON_SIZE)


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
    """Return the icon for `file_path`'s extension, cached per extension.

    Prefers a checked-in asset (see module docstring), then the OS-registered
    shell icon, then a plain gray square when neither is available.
    """
    suffix = Path(file_path).suffix.lower() or ".file"
    if suffix in _icon_cache:
        return _icon_cache[suffix]

    icon = _static_asset_icon(suffix)
    if icon is None and _SHELL_ICONS_AVAILABLE:
        try:
            icon = _shell_icon_for_suffix(suffix)
        except Exception:
            icon = None
    if icon is None:
        icon = tk.PhotoImage(width=16, height=16)
        icon.put("#757575", to=(0, 0, 16, 16))

    _icon_cache[suffix] = icon
    return icon


def get_icon(name: str, size: int = _RIBBON_ICON_SIZE) -> Any | None:
    """Return a ribbon/action icon by logical name (e.g. "search"), cached.

    Returns None when no asset exists yet for that name - callers should
    fall back to a text-only control rather than a missing image. `size`
    defaults to the ribbon tab buttons' 32px; pass 16 for an inline control
    like the search bar's Go button, to match the file-type badges' size.
    """
    cache_key = f"ribbon:{name}:{size}"
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]

    icon = _load_asset(_ASSETS_DIR / f"{name}.png", size)
    if icon is not None:
        _icon_cache[cache_key] = icon
    return icon
