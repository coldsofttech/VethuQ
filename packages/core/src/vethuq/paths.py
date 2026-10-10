"""Where VethuQ keeps its data: the database, backups, run files and logs.

    <data root>/
        db/             vethuq.db
        db/backups/     database backups (unless relocated)
        run/            runtime coordination files
        logs/           log files
        policy/         the cached policy and its state

The data root is the `VETHUQ_HOME` environment variable if set, else the location saved
in the per-user `db.json`, else the platform default. Everything here is read-only: it
reports paths and creates nothing on disk.
"""

from __future__ import annotations

from pathlib import Path

from vethuq._paths import _Paths

__all__ = ["Paths"]


class Paths:
    DB_NAME: str = _Paths.DB_FILENAME
    CONFIG_FILENAME: str = _Paths.LOCATION_FILENAME
    ENV_VAR: str = _Paths.ENV_VAR

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
    def config_file() -> Path:
        """The per-user `db.json` that stores a relocated data root."""
        return _Paths.location_file()
