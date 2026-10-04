"""What the ribbon's buttons do."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RibbonActions:
    """What the ribbon's buttons do - supplied by the window, which owns the views."""

    show_search: Callable[[], None]
    add_folder: Callable[[], None]
    add_file: Callable[[], None]
    show_source_list: Callable[[], None]
    toggle_pause_resume: Callable[[], None]
    stop: Callable[[], None]
    delete_source: Callable[[], None]
    show_about: Callable[[], None]
    show_status: Callable[[str], None]
