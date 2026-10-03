"""On-disk layout of VethuQ's per-user data directory.

    <data root>/            (e.g. %APPDATA%\\VethuQ on Windows)
        db/                 vethuq.db (+ -wal / -shm)
        run/                index.lock, index.control, index_state.json
        logs/               database.log, index.log, ui.log, cli.log

Everything is derived from the database path so a caller (or a test) that
points at its own `db_path` gets its own `run/` and `logs/` next to `db/`.

The data root can be relocated. It is resolved in this order:

    1. the `VETHUQ_HOME` environment variable
    2. the location saved by `vethuq settings location set` - a small JSON file
       (`location.json`) in the per-user config directory that stores only the path
    3. the platform default (e.g. %APPDATA%\\VethuQ on Windows)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


class Paths:
    APP_NAME = "VethuQ"
    DB_FILENAME = "vethuq.db"
    DB_DIRNAME = "db"
    RUN_DIRNAME = "run"
    LOGS_DIRNAME = "logs"

    ENV_VAR = "VETHUQ_HOME"
    LOCATION_FILENAME = "location.json"
    LOCATION_KEY = "location"
    _DATA_DIRNAMES = (DB_DIRNAME, RUN_DIRNAME, LOGS_DIRNAME)

    @staticmethod
    def platform_data_root() -> Path:
        """The platform's default per-user data directory, ignoring any override."""
        return Path(user_data_dir(Paths.APP_NAME, appauthor=False))

    @staticmethod
    def location_file() -> Path:
        """The JSON file that stores the configured data root (and nothing else)."""
        return Path(user_config_dir(Paths.APP_NAME, appauthor=False)) / Paths.LOCATION_FILENAME

    @staticmethod
    def env_location() -> Path | None:
        """The data root set through `VETHUQ_HOME`, if any."""
        value = os.environ.get(Paths.ENV_VAR, "").strip()
        return Path(value).expanduser() if value else None

    @staticmethod
    def configured_location() -> Path | None:
        """The data root saved by `vethuq settings location set`, if any."""
        try:
            data = json.loads(Paths.location_file().read_text(encoding="utf-8"))
            value = data.get(Paths.LOCATION_KEY)
        except (OSError, ValueError, AttributeError):
            return None
        return Path(value) if isinstance(value, str) and value.strip() else None

    @staticmethod
    def resolve_data_root() -> Path:
        """Env var, then saved location, then the platform default."""
        return Paths.env_location() or Paths.configured_location() or Paths.platform_data_root()

    @staticmethod
    def default_data_root() -> Path:
        """The directory VethuQ keeps all its data under (see the module docstring)."""
        return Paths.resolve_data_root()

    @staticmethod
    def save_location(path: Path) -> None:
        """Persist `path` as the data root (atomically, so a crash can't leave a torn file)."""
        file = Paths.location_file()
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps({Paths.LOCATION_KEY: str(path)}), encoding="utf-8")
        tmp.replace(file)

    @staticmethod
    def clear_location() -> None:
        """Forget the saved location so the platform default applies again."""
        Paths.location_file().unlink(missing_ok=True)

    @staticmethod
    def plan_move(source: Path, target: Path) -> list[Path]:
        """The data folders under `source` that moving to `target` would relocate.

        Raises `ValueError` if the move is unsafe: the same place, one inside the other,
        or `target` already holding VethuQ data.
        """
        src, dst = source.resolve(), target.resolve()
        if src == dst:
            raise ValueError("That is already the current location.")
        if src in dst.parents or dst in src.parents:
            raise ValueError("The new location can't be inside the current one, or vice versa.")
        for name in Paths._DATA_DIRNAMES:
            if (dst / name).exists() and any((dst / name).iterdir()):
                raise ValueError(f"'{dst / name}' already contains data.")
        return [source / name for name in Paths._DATA_DIRNAMES if (source / name).is_dir()]

    @staticmethod
    def _detach_log_handlers(folders: list[Path]) -> None:
        """Close and remove file log handlers writing under `folders`.

        Releases the files so they can be deleted on Windows, and stops a later log call
        from reopening a file in a folder that no longer exists.
        """
        roots = [folder.resolve() for folder in folders]
        loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
        for logger in loggers:
            if not isinstance(logger, logging.Logger):
                continue
            for handler in list(logger.handlers):
                name = getattr(handler, "baseFilename", None)
                if name and any(root in Path(name).resolve().parents for root in roots):
                    logger.removeHandler(handler)
                    handler.close()

    @staticmethod
    def move_data(source: Path, target: Path) -> None:
        """Move the db/, run/ and logs/ folders from `source` to `target`.

        Copies first and only removes the originals once every copy succeeded, so a
        failure part-way leaves the original data intact. The caller saves the new
        location afterwards and must ensure no index run is active.
        """
        folders = Paths.plan_move(source, target)
        db_file = source / Paths.DB_DIRNAME / "vethuq.db"
        if db_file.exists():  # fold the WAL into the main file so the copy is complete
            conn = sqlite3.connect(db_file)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
        target.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        try:
            for folder in folders:
                shutil.copytree(folder, target / folder.name, dirs_exist_ok=True)
                copied.append(target / folder.name)
        except BaseException:
            for folder in copied:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        Paths.save_location(target)
        Paths._detach_log_handlers(folders)
        for folder in folders:
            shutil.rmtree(folder, ignore_errors=True)

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
