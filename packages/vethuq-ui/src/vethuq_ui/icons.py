"""File-type badge and ribbon action icons.

Both kinds load from the checked-in assets under `assets/icons/`
(generated via `scripts/dev/generate_icons.py`):

- `Icons.for_file` - file-type badges for the search results list. An extension without a
  generated asset yet shows the generic file icon, then a plain grey square if even that is
  missing.
- `Icons.get` - ribbon action icons (Search, Sources, GPU, ...), looked up by logical name
  rather than file suffix. Returns None for a name with no asset yet, so callers can fall back
  to a text-only control.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from PIL import Image, ImageTk


class Icons:
    _DIR = Path(__file__).resolve().parent / "assets" / "icons"
    FILE_SIZE = 16
    RIBBON_SIZE = 32
    GENERIC_FILE = "file"
    MISSING_COLOUR = "#757575"

    # .jpeg has no asset of its own - it's the same format as .jpg.
    _SUFFIX_ALIASES = {".jpeg": "jpg"}

    _cache: dict[str, Any] = {}

    @staticmethod
    def load(path: Path, size: int) -> Any | None:
        """The image at `path` scaled to `size` x `size`, or None if there is no such file."""
        if not path.is_file():
            return None
        image = Image.open(path).convert("RGBA")
        if image.size != (size, size):
            image = image.resize((size, size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

    @staticmethod
    def for_file(file_path: str | Path) -> Any:
        """The badge for `file_path`'s extension, cached per extension."""
        suffix = Path(file_path).suffix.lower() or ".file"
        key = f"file:{suffix}"
        if key not in Icons._cache:
            stem = Icons._SUFFIX_ALIASES.get(suffix, suffix.lstrip("."))
            icon = Icons.load(Icons._DIR / f"{stem}.png", Icons.FILE_SIZE)
            if icon is None:
                icon = Icons.load(Icons._DIR / f"{Icons.GENERIC_FILE}.png", Icons.FILE_SIZE)
            if icon is None:
                icon = tk.PhotoImage(width=Icons.FILE_SIZE, height=Icons.FILE_SIZE)
                icon.put(Icons.MISSING_COLOUR, to=(0, 0, Icons.FILE_SIZE, Icons.FILE_SIZE))
            Icons._cache[key] = icon
        return Icons._cache[key]

    @staticmethod
    def get(name: str, size: int = RIBBON_SIZE) -> Any | None:
        """A ribbon/action icon by logical name (e.g. "search"), cached.

        Returns None when no asset exists yet for that name - callers should fall back to a
        text-only control rather than a missing image. `size` defaults to the ribbon buttons'
        32px; pass 16 for an inline control like the search bar's Go button, to match the
        file-type badges' size.
        """
        key = f"ribbon:{name}:{size}"
        if key not in Icons._cache:
            icon = Icons.load(Icons._DIR / f"{name}.png", size)
            if icon is None:
                return None
            Icons._cache[key] = icon
        return Icons._cache[key]


class Brand:
    """The VethuQ icon: the window/taskbar icon and the small logo inside the app."""

    _DIR = Path(__file__).resolve().parent / "assets" / "brand"
    _cache: dict[int, Any] = {}

    @staticmethod
    def logo(size: int) -> Any | None:
        """The icon as a `size` x `size` image, or None if the asset is missing."""
        if size not in Brand._cache:
            image = Icons.load(Brand._DIR / "vethuq.png", size)
            if image is None:
                return None
            Brand._cache[size] = image
        return Brand._cache[size]

    @staticmethod
    def apply_window_icon(window: tk.Tk | tk.Toplevel) -> None:
        """Title bar and taskbar icon; best-effort, a missing asset leaves Tk's default."""
        try:
            window.iconbitmap(default=str(Brand._DIR / "vethuq.ico"))
        except tk.TclError:
            image = Brand.logo(64)
            if image is not None:
                window.iconphoto(True, image)
