"""The device-scoped folder: what belongs to the computer, not to one account.

The credit ledger (what was spent, and the grants it was spent from) and the licences are kept
here, in one SQLite file (`device.db`), so every OS account on the computer and the background
service share them: a second account does not get a second free allowance, and a licence installed
once works for all of them. It is a deterrent, not a lock: the file is writable by local accounts.

Where it lives, in order:

1. `VETHUQ_DEVICE_HOME`, if set.
2. For a database in an account's standard data folder (its resolved data root, or a folder named
   `VethuQ`, which is what the installed service is pointed at), the platform's shared folder:
   `%PROGRAMDATA%\\VethuQ` on Windows, `/Users/Shared/VethuQ` on macOS, `/var/lib/vethuq` on Linux.
   Where that can't be created or written (a pip install without the rights), `device/` in the
   account's own data folder instead (scope `user`): nothing is shared then, and
   `vethuq settings location show` says so.
3. A database anywhere else (a test, a copy, `--db` of a custom folder) keeps `device/` next to it
   (scope `database`), so such a database is self-contained.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vethuq._errors import _DataFolderNotWritableError
from vethuq._paths.paths import _Paths

_logger = logging.getLogger("vethuq.database")


@dataclass(frozen=True)
class _DeviceLocation:
    path: Path
    scope: str  # `custom` (VETHUQ_DEVICE_HOME), `device` (shared), `user` (fallback), `database`

    @property
    def database(self) -> Path:
        return self.path / _DeviceFolder.DB_FILENAME

    @property
    def shared(self) -> bool:
        return self.scope in ("custom", "device")


class _DeviceFolder:
    ENV_VAR = "VETHUQ_DEVICE_HOME"
    DIRNAME = "device"
    DB_FILENAME = "device.db"
    TIMEOUT_SECONDS = 5
    # Windows' built-in "Users" group (a well-known SID, so it works in every language).
    USERS_SID = "*S-1-5-32-545"

    _cache: dict[tuple[str, str, str], _DeviceLocation] = {}
    _warned: set[str] = set()

    @staticmethod
    def _is_windows() -> bool:
        return os.name == "nt"

    # ----- choosing ---------------------------------------------------------------------------

    @classmethod
    def resolve(cls, db_path: Path) -> _DeviceLocation:
        """The device folder for a database (created and checked, once per process)."""
        env = os.environ.get(cls.ENV_VAR, "").strip()
        root = _Paths.data_root(Path(db_path))
        key = (str(root), env, str(_Paths.platform_device_root()))
        found = cls._cache.get(key)
        if found is not None and found.path.is_dir():
            return found
        found = cls._choose(root, env)
        cls._cache[key] = found
        return found

    @classmethod
    def _choose(cls, root: Path, env: str) -> _DeviceLocation:
        if env:
            path = Path(env).expanduser()
            try:
                cls.prepare(path)
            except OSError as exc:
                raise _DataFolderNotWritableError(
                    f"VethuQ can't use the device folder {path} ({exc.strerror or exc}).",
                    f"Check its permissions, or change or unset {cls.ENV_VAR}.",
                ) from exc
            return _DeviceLocation(path, "custom")
        own = root / cls.DIRNAME
        if not _Paths.is_standard_root(root):
            cls.prepare(own, shared=False)
            return _DeviceLocation(own, "database")
        shared = _Paths.platform_device_root()
        try:
            cls.prepare(shared)
            return _DeviceLocation(shared, "device")
        except OSError as exc:
            if str(shared) not in cls._warned:
                cls._warned.add(str(shared))
                _logger.warning(
                    "The device folder %s can't be used (%s); this account keeps its own "
                    "licences and credits in %s",
                    shared,
                    exc.strerror or exc,
                    own,
                )
        cls.prepare(own, shared=False)
        return _DeviceLocation(own, "user")

    # ----- preparing --------------------------------------------------------------------------

    @classmethod
    def prepare(cls, path: Path, shared: bool = True) -> None:
        """Create the folder (open to every local account when `shared`) and prove it can be
        written to. Raises `OSError` when it can't."""
        existed = path.is_dir()
        path.mkdir(parents=True, exist_ok=True)
        if shared and not existed:
            cls._open_to_all(path)
        with tempfile.TemporaryFile(dir=path):
            pass

    @classmethod
    def _open_to_all(cls, path: Path) -> None:
        """Let every local account create and change files here (best effort)."""
        if cls._is_windows():
            # Inherited by everything created inside, including the database files.
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(  # noqa: S603 - fixed arguments; the SID is a constant
                    ["icacls", str(path), "/grant", f"{cls.USERS_SID}:(OI)(CI)M"],  # noqa: S607
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            return
        with contextlib.suppress(OSError):
            path.chmod(0o1777)  # world-writable with the sticky bit, like /tmp

    @classmethod
    def touch(cls, location: _DeviceLocation) -> None:
        """Make sure the database file exists and, for a shared folder, that every account can
        write it (SQLite makes its rollback journal with the file's own permissions)."""
        file = location.database
        if not file.exists():
            previous = os.umask(0)
            try:
                fd = os.open(file, os.O_CREAT | os.O_RDWR, 0o666)
                os.close(fd)
            finally:
                os.umask(previous)
        if location.shared and not cls._is_windows():
            with contextlib.suppress(OSError):
                if file.stat().st_mode & 0o666 != 0o666:
                    file.chmod(0o666)

    # ----- licences ---------------------------------------------------------------------------


class _DeviceLicences:
    """The licence tokens, by add-on id, in the device database (plain `sqlite3`, like the add-on
    settings, so they can be read while VethuQ's own database is opening or refused)."""

    def __init__(self, db_path: Path) -> None:
        self.location = _DeviceFolder.resolve(db_path)

    def _connect(self) -> sqlite3.Connection:
        _DeviceFolder.touch(self.location)
        conn = sqlite3.connect(self.location.database, timeout=_DeviceFolder.TIMEOUT_SECONDS)
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS licences (addon_id TEXT PRIMARY KEY, token TEXT NOT NULL)"
        )
        return conn

    def all(self) -> dict[str, str]:
        if not self.location.database.exists():
            return {}
        try:
            conn = sqlite3.connect(
                f"{self.location.database.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=_DeviceFolder.TIMEOUT_SECONDS,
            )
            try:
                rows = conn.execute("SELECT addon_id, token FROM licences").fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return {}
        return {addon: token for addon, token in rows if token}

    def get(self, addon_id: str) -> str | None:
        return self.all().get(addon_id)

    def set(self, addon_id: str, token: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO licences (addon_id, token) VALUES (?, ?) "
                    "ON CONFLICT(addon_id) DO UPDATE SET token = excluded.token",
                    (addon_id, token),
                )
        finally:
            conn.close()

    def reset(self, addon_id: str) -> None:
        if not self.location.database.exists():
            return
        conn = self._connect()
        try:
            with conn:
                conn.execute("DELETE FROM licences WHERE addon_id = ?", (addon_id,))
        finally:
            conn.close()
