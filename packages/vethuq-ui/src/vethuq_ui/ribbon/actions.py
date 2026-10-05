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
    show_gpu: Callable[[], None]
    show_ocr_retry: Callable[[], None]
    show_ocr_engine: Callable[[], None]
    show_ocr_languages: Callable[[], None]
    show_search_field: Callable[[str], None]
    show_removed_retention: Callable[[], None]
    show_stability_check: Callable[[], None]
    show_thread_workers: Callable[[], None]
    show_stale_lock: Callable[[], None]
    show_background_service: Callable[[], None]
    show_db_field: Callable[[str], None]
    show_log_field: Callable[[str], None]
    show_app_location: Callable[[], None]
    show_backups_location: Callable[[], None]
