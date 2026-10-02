"""File logging for the desktop UI."""

from __future__ import annotations

from pathlib import Path

from vethuq_core.db import Db
from vethuq_core.logs import Logs


class UiLogging:
    logger = Logs.get_logger("ui")

    @staticmethod
    def configure(db_path: Path | None) -> None:
        """Log to `ui.log` in the data directory's `logs/` folder so a UI bug like a
        silently-failing button command shows up somewhere instead of only in a
        console no one is watching (Tk swallows exceptions raised inside
        `command=` callbacks). The verbosity follows the `log_level` setting.
        """
        Logs.setup("ui", db_path or Db.default_db_path())
