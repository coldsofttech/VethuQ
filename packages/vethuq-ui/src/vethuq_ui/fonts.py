"""Fonts for Telugu text in the desktop app.

Windows 10 and 11 ship Telugu fonts (Nirmala UI, Gautami, Vani), and the app uses one of them when
it needs to show Telugu. Where none is there - a stripped-down image, an old install - the
installer puts Noto Sans Telugu (SIL Open Font License) in `fonts\\` beside the app when Telugu is
chosen, and it is loaded for this process only (`AddFontResourceEx` with `FR_PRIVATE`: nothing is
installed into Windows, so no administrator rights are needed and uninstalling leaves nothing
behind).

English text is never touched: a widget switches to a Telugu-capable font only while it holds
Telugu, and nothing is looked up or loaded until then.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vethuq_core.languages import Scripts
from vethuq_core.logs import Logs

if TYPE_CHECKING:
    import tkinter as tk
    import tkinter.font as tkfont

_logger = Logs.get_logger("ui")


class TeluguFont:
    # Fonts Windows ships that cover Telugu (and Latin), best first.
    NATIVE_FAMILIES = ("Nirmala UI", "Gautami", "Vani")
    # The fallback the installer provides. It has Telugu but no Latin letters, so a widget using it
    # for mixed text relies on Windows substituting a font for the Latin ones, which it does.
    BUNDLED_FAMILY = "Noto Sans Telugu"
    FR_PRIVATE = 0x10
    # The attribute caching the resolved font on the Tk root (None once looked for and not found).
    _ATTRIBUTE = "_vethuq_telugu_font"

    @staticmethod
    def fonts_dir() -> Path:
        """Where the fallback font files are: beside the executables in the installed app, in the
        package's assets otherwise."""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent / "fonts"
        return Path(__file__).parent / "assets" / "fonts"

    @staticmethod
    def needs_font(text: str) -> bool:
        """Whether `text` has Telugu in it (anything the default font may not draw)."""
        return Scripts.has_mark_script(text)

    @staticmethod
    def pick(families: Iterable[str]) -> str | None:
        """The family to use out of the installed `families`: a native Telugu font first, then the
        bundled one; None if there is neither."""
        available = {family.casefold(): family for family in families}
        for wanted in (*TeluguFont.NATIVE_FAMILIES, TeluguFont.BUNDLED_FAMILY):
            if wanted.casefold() in available:
                return available[wanted.casefold()]
        return None

    @staticmethod
    def _add_private_font(path: Path) -> int:
        """Make the font file usable by this process only; returns how many fonts it added.

        Windows only (GDI); on any other platform there is nothing to do.
        """
        if sys.platform != "win32":
            return 0
        import ctypes

        return int(ctypes.windll.gdi32.AddFontResourceExW(str(path), TeluguFont.FR_PRIVATE, 0))

    @staticmethod
    def load_bundled(add: Callable[[Path], int] | None = None) -> list[Path]:
        """Load the fallback font files for this process; returns the ones that were added.

        `add` makes one file usable (the Windows call by default; injectable for tests).
        """
        add = add or TeluguFont._add_private_font
        loaded = []
        for path in sorted(TeluguFont.fonts_dir().glob("*.ttf")):
            try:
                if add(path) > 0:
                    loaded.append(path)
                else:
                    _logger.warning("Could not load the font %s", path)
            except OSError:
                _logger.exception("Could not load the font %s", path)
        return loaded

    @staticmethod
    def resolve(
        list_families: Callable[[], Iterable[str]], add: Callable[[Path], int] | None = None
    ) -> str | None:
        """The family to show Telugu in, loading the bundled font only if Windows has no native
        one; None if neither works. `list_families` returns the families Tk can see now."""
        family = TeluguFont.pick(list_families())
        if family is not None and family != TeluguFont.BUNDLED_FAMILY:
            return family
        if TeluguFont.load_bundled(add):
            return TeluguFont.pick(list_families())
        return family

    @staticmethod
    def font_for(root: tk.Misc) -> tkfont.Font | None:
        """A Tk font in the right family at the default size, found once and kept; None when no
        Telugu font could be found (the text is then drawn by whatever Windows substitutes)."""
        cached: Any = getattr(root, TeluguFont._ATTRIBUTE, False)
        if cached is not False:
            return cached
        import tkinter.font as tkfont

        family = TeluguFont.resolve(lambda: tkfont.families(root))
        font = None
        if family is None:
            _logger.warning("No font that can draw Telugu was found")
        else:
            default = tkfont.nametofont("TkDefaultFont", root=root)
            font = tkfont.Font(root=root, family=family, size=default.cget("size"))
            _logger.info("Showing Telugu in %s", family)
        setattr(root, TeluguFont._ATTRIBUTE, font)
        return font
