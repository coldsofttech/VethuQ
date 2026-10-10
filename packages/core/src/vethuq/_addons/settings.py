"""Add-on settings, kept in the VethuQ `settings` table as `addon.<id>.<key>`.

They are read and written with plain `sqlite3`, so an add-on can use them from a hook, while the
database is opening, and on a database VethuQ refuses to open.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from vethuq._errors import _InvalidSettingValueError


class _AddonSettingsStore:
    KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
    TIMEOUT_SECONDS = 5

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

    def get(self, key: str, default: str | None = None) -> str | None:
        full = self.full_key(key)
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
        conn = self._connect()
        try:
            with conn:
                conn.execute("DELETE FROM settings WHERE key = ?", (full,))
        finally:
            conn.close()
