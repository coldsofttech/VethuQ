"""File logging for the desktop UI."""

from __future__ import annotations

import logging
from pathlib import Path

from vethuq_core.db import Db


class UiLogging:
    LOG_FILENAME = "vethuq-ui.log"
    logger = logging.getLogger("vethuq_ui")

    @staticmethod
    def configure(db_path: Path | None) -> None:
        """Log to `vethuq-ui.log` next to the database (same dir as the .db,
        lock/state files, etc.) so a UI bug like a silently-failing button
        command shows up somewhere instead of only in a console no one is
        watching (Tk swallows exceptions raised inside `command=` callbacks).
        """
        if UiLogging.logger.handlers:
            return
        log_path = (db_path or Db.default_db_path()).parent / UiLogging.LOG_FILENAME
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        UiLogging.logger.addHandler(handler)
        UiLogging.logger.setLevel(logging.INFO)
