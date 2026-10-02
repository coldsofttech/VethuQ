"""On-disk layout of VethuQ's per-user data directory.

    <data root>/            (e.g. %APPDATA%\\VethuQ on Windows)
        db/                 vethuq.db (+ -wal / -shm)
        run/                index.lock, index.control, index_state.json
        logs/               database.log, index.log, ui.log, cli.log

Everything is derived from the database path so a caller (or a test) that
points at its own `db_path` gets its own `run/` and `logs/` next to `db/`.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir


class Paths:
    APP_NAME = "VethuQ"
    DB_FILENAME = "vethuq.db"
    DB_DIRNAME = "db"
    RUN_DIRNAME = "run"
    LOGS_DIRNAME = "logs"

    @staticmethod
    def default_data_root() -> Path:
        """The per-user directory VethuQ keeps all its data under."""
        return Path(user_data_dir(Paths.APP_NAME, appauthor=False))

    @staticmethod
    def data_root(db_path: Path) -> Path:
        """The data root a database path belongs to.

        A database in a `db/` folder belongs to that folder's parent; a database
        anywhere else (e.g. a test's temp dir) uses its own directory as the root.
        """
        parent = db_path.parent
        return parent.parent if parent.name == Paths.DB_DIRNAME else parent

    @staticmethod
    def run_dir(db_path: Path) -> Path:
        """Folder for runtime coordination files (lock, control, state); created on demand."""
        path = Paths.data_root(db_path) / Paths.RUN_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def logs_dir(db_path: Path) -> Path:
        """Folder for log files; created on demand."""
        path = Paths.data_root(db_path) / Paths.LOGS_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path
