"""On-disk layout of VethuQ's per-user data directory.

    <data root>/            (e.g. %APPDATA%\\VethuQ on Windows)
        db/                 vethuq.db (+ -wal / -shm)
        db/backups/         compressed database backups (default; can be relocated)
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
import tempfile
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

from vethuq_core.errors import DataFolderNotWritableError, InvalidConfigError
from vethuq_core.hints import Hints


class Paths:
    APP_NAME = "VethuQ"
    DB_FILENAME = "vethuq.db"
    DB_DIRNAME = "db"
    RUN_DIRNAME = "run"
    LOGS_DIRNAME = "logs"

    ENV_VAR = "VETHUQ_HOME"
    LOCATION_FILENAME = "location.json"
    LOCATION_KEY = "location"
    BACKUPS_KEY = "backups"
    BACKUPS_DIRNAME = "backups"
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
    def _read_pointer() -> dict[str, str]:
        """The saved settings from `location.json` (empty if missing or unreadable)."""
        try:
            data = json.loads(Paths.location_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}

    @staticmethod
    def check_config() -> None:
        """Raise `InvalidConfigError` if the saved settings or `VETHUQ_HOME` can't be used."""
        file = Paths.location_file()
        if file.exists():
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise InvalidConfigError(
                    f"The settings file {file} can't be read ({exc}).",
                    "Fix it, or delete the file to go back to the default location.",
                ) from exc
            if not isinstance(data, dict):
                raise InvalidConfigError(
                    f"The settings file {file} is not in the expected format.",
                    "Delete the file to go back to the default location.",
                )
        env = Paths.env_location()
        if env is not None and env.exists() and not env.is_dir():
            raise InvalidConfigError(
                f"{Paths.ENV_VAR} points to {env}, which is a file, not a folder.",
                f"Set {Paths.ENV_VAR} to a folder, or unset it.",
            )

    @staticmethod
    def ensure_writable(folder: Path) -> None:
        """Create `folder` and prove it can be written to, or raise `DataFolderNotWritableError`."""
        try:
            folder.mkdir(parents=True, exist_ok=True)
            # A uniquely named, self-deleting file: several processes (e.g. parallel test
            # workers) can probe the same folder at once without clashing over one name.
            with tempfile.TemporaryFile(dir=folder):
                pass
        except OSError as exc:
            raise DataFolderNotWritableError(
                f"VethuQ can't write to its data folder {folder} ({exc.strerror or exc}).",
                f"Check the folder's permissions and free space, or choose another with "
                f"'{Hints.command('settings location set')}' or the {Paths.ENV_VAR} setting.",
            ) from exc

    @staticmethod
    def _write_pointer(data: dict[str, str]) -> None:
        """Persist `data` atomically, or remove the file once nothing is left to store."""
        file = Paths.location_file()
        if not data:
            file.unlink(missing_ok=True)
            return
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(file)

    @staticmethod
    def configured_location() -> Path | None:
        """The data root saved by `vethuq settings location set`, if any."""
        value = Paths._read_pointer().get(Paths.LOCATION_KEY)
        return Path(value) if value else None

    @staticmethod
    def configured_backups_location() -> Path | None:
        """The backups folder saved by `vethuq settings location backups set`, if any."""
        value = Paths._read_pointer().get(Paths.BACKUPS_KEY)
        return Path(value) if value else None

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
        Paths._write_pointer({**Paths._read_pointer(), Paths.LOCATION_KEY: str(path)})

    @staticmethod
    def clear_location() -> None:
        """Forget the saved data root so the platform default applies again."""
        data = Paths._read_pointer()
        data.pop(Paths.LOCATION_KEY, None)
        Paths._write_pointer(data)

    @staticmethod
    def save_backups_location(path: Path) -> None:
        """Persist `path` as the folder backups are kept in."""
        Paths._write_pointer({**Paths._read_pointer(), Paths.BACKUPS_KEY: str(path)})

    @staticmethod
    def clear_backups_location() -> None:
        """Forget the saved backups folder so backups go back to `db/backups`."""
        data = Paths._read_pointer()
        data.pop(Paths.BACKUPS_KEY, None)
        Paths._write_pointer(data)

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
    def backups_dir(db_path: Path, *, create: bool = True) -> Path:
        """Folder for database backups: the configured one, else `db/backups` next to the db."""
        path = Paths.configured_backups_location() or db_path.parent / Paths.BACKUPS_DIRNAME
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def logs_dir(db_path: Path) -> Path:
        """Folder for log files; created on demand."""
        path = Paths.data_root(db_path) / Paths.LOGS_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path
