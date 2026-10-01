"""Rich styles for the CLI, drawn from the shared palette.

Terminals are mostly dark, so these use the palette's dark scheme. Where a style isn't
named here (the dim `bright_black` notes, `bold`, `underline`) the terminal's own theme
is the better choice.
"""

from __future__ import annotations

from vethuq_core.branding import Palette


class Theme:
    PRIMARY = Palette.get("primary", "dark")
    ACCENT = Palette.get("accent", "dark")
    HIGHLIGHT = Palette.get("highlight", "dark")
    ON_HIGHLIGHT = Palette.get("on-highlight", "dark")
    SUCCESS = Palette.get("success", "dark")
    WARNING = Palette.get("warning", "dark")
    DANGER = Palette.get("danger", "dark")

    ERROR = f"bold {DANGER}"  # an error message
    OK = f"bold {SUCCESS}"  # something succeeded, or a finished state
    PAUSED = f"bold {WARNING}"  # a paused run
    NOTICE = WARNING  # a neutral heads-up, e.g. "No matches found."
    INFO = f"bold {PRIMARY}"  # an in-progress or informational state
    VALUE = PRIMARY  # a setting's value
    LABEL = HIGHLIGHT  # a field label in a table
    COMMAND = f"bold {ACCENT}"  # a command the user can run
    BRAND = f"bold {PRIMARY}"  # the app banner
