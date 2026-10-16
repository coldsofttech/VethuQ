"""Add-on settings, kept in the VethuQ `settings` table as `addon.<id>.<key>`.

They are read and written with plain `sqlite3`, so an add-on can use them from a hook, while the
database is opening, and on a database VethuQ refuses to open.

The one exception is `licence`: a licence belongs to the computer, so it is kept in the device
folder (see `vethuq._paths.device`), shared by every account and the background service. A licence
an older version saved in the `settings` table is still read, until it is replaced or removed.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from vethuq._errors import _InvalidSettingValueError
from vethuq._paths.device import _DeviceLicences


class _AddonSettingsStore:
    KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
    TIMEOUT_SECONDS = 5
    DEVICE_KEY = "licence"  # the setting that is kept per device, not per database

    def __init__(self, db_path: Path, addon_id: str) -> None:
        self.db_path = Path(db_path)
        self.addon_id = addon_id

    def full_key(self, key: str) -> str:
        if not self.KEY_RE.match(key):
            raise _InvalidSettingValueError(
                f"{key!r} isn't a valid add-on setting name.",
                "Use lowercase letters, digits and underscores, starting with a letter.",
            )
        return f"addon.{self.addon_id}.{key}"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=self.TIMEOUT_SECONDS)

    @classmethod
    def licences(cls, db_path: Path) -> dict[str, str]:
        """Every add-on's `licence` setting, by add-on id (empty ones left out): the device's, and
        any an older version kept in the database that the device doesn't have."""
        return {**cls._database_licences(db_path), **_DeviceLicences(Path(db_path)).all()}

    @classmethod
    def _database_licences(cls, db_path: Path) -> dict[str, str]:
        try:  # read-only, so a missing database isn't created by asking
            conn = sqlite3.connect(
                f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True, timeout=cls.TIMEOUT_SECONDS
            )
            try:
                rows = conn.execute(
                    "SELECT key, value FROM settings WHERE key LIKE 'addon.%.licence'"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return {}
        found = {key.removeprefix("addon.").removesuffix(".licence"): value for key, value in rows}
        return {addon: value for addon, value in found.items() if value}

    def get(self, key: str, default: str | None = None) -> str | None:
        full = self.full_key(key)
        if key == self.DEVICE_KEY:
            found = _DeviceLicences(self.db_path).get(self.addon_id)
            if found is not None:
                return found
        try:
            conn = self._connect()
            try:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (full,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return default
        return row[0] if row is not None else default

    def set(self, key: str, value: str) -> None:
        full = self.full_key(key)
        if key == self.DEVICE_KEY:
            _DeviceLicences(self.db_path).set(self.addon_id, str(value))
            self._forget_in_database(full)  # no stale copy of an older version's
            return
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (full, str(value)),
                )
        finally:
            conn.close()

    def reset(self, key: str) -> None:
        full = self.full_key(key)
        if key == self.DEVICE_KEY:
            _DeviceLicences(self.db_path).reset(self.addon_id)
        conn = self._connect()
        try:
            with conn:
                conn.execute("DELETE FROM settings WHERE key = ?", (full,))
        finally:
            conn.close()

    def _forget_in_database(self, full: str) -> None:
        try:
            conn = self._connect()
            try:
                with conn:
                    conn.execute("DELETE FROM settings WHERE key = ?", (full,))
            finally:
                conn.close()
        except sqlite3.Error:  # no database (yet) is fine: there is nothing stale to remove
            return
