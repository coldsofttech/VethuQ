"""Where VethuQ keeps its data: the database, backups, run files and logs.

    <data root>/
        db/             vethuq.db
        db/backups/     database backups (unless relocated)
        run/            runtime coordination files
        logs/           log files
        policy/         the cached policy and its state

    <device folder>/    shared by every account on the computer (see `device_dir`)
        device.db       licences and the credit ledger

The data root is the `VETHUQ_HOME` environment variable if set, else the location saved
in the per-user `db.json`, else the platform default. The getters only report paths and
create nothing; `relocate`, `reset_location` and the backups equivalents change where data lives.
"""

from __future__ import annotations

from pathlib import Path

from vethuq._paths import _Paths
from vethuq._paths.device import _DeviceFolder

__all__ = ["Paths"]


class Paths:
    DB_NAME: str = _Paths.DB_FILENAME
    CONFIG_FILENAME: str = _Paths.LOCATION_FILENAME
    ENV_VAR: str = _Paths.ENV_VAR
    DEVICE_ENV_VAR: str = _DeviceFolder.ENV_VAR

    @staticmethod
    def data_root() -> Path:
        """The folder all VethuQ data lives under."""
        return _Paths.resolve_data_root()

    @staticmethod
    def db_dir() -> Path:
        """The folder holding the database."""
        return Paths.data_root() / _Paths.DB_DIRNAME

    @staticmethod
    def db_path() -> Path:
        """The database file."""
        return Paths.db_dir() / Paths.DB_NAME

    @staticmethod
    def backups_dir() -> Path:
        """The folder database backups are kept in."""
        return _Paths.configured_backups_location() or Paths.db_dir() / _Paths.BACKUPS_DIRNAME

    @staticmethod
    def run_dir() -> Path:
        """The folder for runtime coordination files."""
        return Paths.data_root() / _Paths.RUN_DIRNAME

    @staticmethod
    def logs_dir() -> Path:
        """The folder for log files."""
        return Paths.data_root() / _Paths.LOGS_DIRNAME

    @staticmethod
    def policy_dir() -> Path:
        """The folder for the cached policy and its state."""
        return Paths.data_root() / _Paths.POLICY_DIRNAME

    @staticmethod
    def device_dir() -> Path:
        """The folder licences and the credit ledger are kept in, shared by every account on this
        computer and by the background service (see `device_scope`). Created, and its permissions
        opened to every account, the first time it is asked for."""
        return _DeviceFolder.resolve(Paths.db_path()).path

    @staticmethod
    def device_scope() -> str:
        """Who shares `device_dir`: `device` (every account on this computer), `custom` (the
        folder `VETHUQ_DEVICE_HOME` names), or `user` (only this account: the shared folder
        couldn't be used, so it keeps its own licences and credits)."""
        return _DeviceFolder.resolve(Paths.db_path()).scope

    @staticmethod
    def config_file() -> Path:
        """The per-user `db.json` that stores a relocated data root."""
        return _Paths.location_file()

    @staticmethod
    def location_source() -> str:
        """Where the data root comes from: `env`, `saved` or `default`."""
        if _Paths.env_location() is not None:
            return "env"
        return "saved" if _Paths.configured_location() is not None else "default"

    @staticmethod
    def default_data_root() -> Path:
        """The platform default data root."""
        return _Paths.default_data_root()

    @staticmethod
    def relocate(target: str | Path, *, move: bool = True) -> Path:
        """Make `target` the data root, moving the existing data there unless `move=False`.

        Raises `ValueError` if the move is not possible (same place, nested, or the target already
        holds data) and `OSError` if the target is not writable. Make sure no index run is active.
        """
        if _Paths.env_location() is not None:
            raise ValueError(f"{Paths.ENV_VAR} is set and overrides the saved location")
        new = Path(target).expanduser().resolve()
        _Paths.ensure_writable(new)
        old = Paths.data_root()
        if move and old.exists():
            _Paths.move_data(old, new)
        else:
            _Paths.save_location(new)
        return new

    @staticmethod
    def reset_location(*, move: bool = True) -> Path:
        """Go back to the platform default data root."""
        default = _Paths.default_data_root()
        if _Paths.env_location() is not None:
            raise ValueError(f"{Paths.ENV_VAR} is set and overrides the saved location")
        if Paths.data_root() == default:
            _Paths.clear_location()
            return default
        if move and Paths.data_root().exists():
            _Paths.move_data(Paths.data_root(), default)
        _Paths.clear_location()
        return default

    @staticmethod
    def set_backups_dir(target: str | Path) -> Path:
        """Keep database backups in `target`."""
        new = Path(target).expanduser().resolve()
        _Paths.ensure_writable(new)
        _Paths.save_backups_location(new)
        return new

    @staticmethod
    def reset_backups_dir() -> Path:
        """Keep database backups next to the database again."""
        _Paths.clear_backups_location()
        return Paths.backups_dir()
