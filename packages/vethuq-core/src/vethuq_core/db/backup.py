"""Compressed database backups, plus restore / reset / repair built on them.

Backups live in `<db folder>/backups/` (or the folder set with
`vethuq settings location backups set`) as `<name>.db.gz`. They are taken with
SQLite's own backup API (not a file copy), so they are consistent even while
the database is open and part of it is still in the `-wal` file.

Three kinds, told apart by their name prefix:

* `auto-...` - taken automatically (at most once per `db_backup_interval_minutes`)
  when the database is opened, and pruned by `db_backup_retention_days`.
* `safety-...` - taken automatically right before `restore`, `reset` or `repair`
  changes the database, so any of them can be undone. Pruned like `auto-...`.
* anything else - a snapshot the user named with `vethuq db backup create`.
  Never pruned automatically.
"""

from __future__ import annotations

import gzip
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vethuq_core.db.connection import Db
from vethuq_core.db.integrity import IntegrityCheckResult
from vethuq_core.db.queries.semantic import Semantic
from vethuq_core.hints import Hints
from vethuq_core.logs import Logs
from vethuq_core.paths import Paths
from vethuq_core.settings import DbSettings, Settings
from vethuq_core.storage import Storage

_logger = Logs.get_logger("database")


class BackupError(Exception):
    """A backup, restore, reset or repair could not be completed."""


@dataclass(frozen=True)
class BackupInfo:
    name: str
    path: Path
    size: int
    created_at: datetime
    kind: str  # "auto", "safety" or "manual"


class Backup:
    DIRNAME = "backups"
    SUFFIX = ".db.gz"
    AUTO_PREFIX = "auto-"
    SAFETY_PREFIX = "safety-"
    LAST_RUN_AT_KEY = "backup_last_run_at"
    # Retention never removes the newest few automatic/safety backups, so a long
    # stretch of unnoticed corruption can't age every good backup out.
    MIN_KEPT = 3
    _NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

    @staticmethod
    def directory(db_path: Path) -> Path:
        """The folder backups are kept in (see `Paths.backups_dir`); created on demand."""
        return Paths.backups_dir(db_path)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")

    @staticmethod
    def _kind(name: str) -> str:
        if name.startswith(Backup.AUTO_PREFIX):
            return "auto"
        if name.startswith(Backup.SAFETY_PREFIX):
            return "safety"
        return "manual"

    @staticmethod
    def _integrity_messages(path: Path) -> list[str]:
        conn = sqlite3.connect(path)
        try:
            return [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        except sqlite3.DatabaseError as exc:
            return [str(exc)]
        finally:
            conn.close()

    @staticmethod
    def _schema_version(path: Path) -> int | None:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] if row else None
        except sqlite3.DatabaseError:
            return None
        finally:
            conn.close()

    @staticmethod
    def _snapshot(db_path: Path, dest: Path, conn: sqlite3.Connection | None = None) -> None:
        """Write a consistent plain copy of the database to `dest`.

        Copies from `conn` if given (a connection already open on the database, e.g.
        mid-migration), otherwise from a fresh connection to `db_path`.
        """
        source = conn or sqlite3.connect(db_path)
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
            if conn is None:
                source.close()

    @staticmethod
    def _compress(plain: Path, dest: Path) -> None:
        tmp = dest.with_name(dest.name + ".tmp")
        with plain.open("rb") as src, gzip.open(tmp, "wb") as out:
            shutil.copyfileobj(src, out)
        tmp.replace(dest)

    @staticmethod
    def create(
        db_path: Path,
        name: str | None = None,
        *,
        prefix: str = "",
        require_ok: bool = True,
        conn: sqlite3.Connection | None = None,
    ) -> BackupInfo:
        """Take a compressed backup of the database now and return it.

        `name` is for a user-named snapshot (letters, digits, `.`, `_`, `-`); without
        one a timestamped name is generated. With `require_ok` the copy must pass
        `PRAGMA integrity_check` first - an unusable backup is worse than none.
        """
        if not db_path.exists():
            raise BackupError("There is no database to back up yet.")
        if name is not None:
            if not Backup._NAME_PATTERN.match(name):
                raise BackupError(
                    "A backup name may only use letters, digits, '.', '_' and '-' "
                    "(up to 64 characters, starting with a letter or digit)."
                )
            if name.startswith((Backup.AUTO_PREFIX, Backup.SAFETY_PREFIX)):
                raise BackupError(
                    f"Names starting with '{Backup.AUTO_PREFIX}' or '{Backup.SAFETY_PREFIX}' "
                    "are reserved."
                )
        directory = Backup.directory(db_path)
        final_name = name or f"{prefix}{Backup._timestamp()}"
        dest = directory / f"{final_name}{Backup.SUFFIX}"
        if dest.exists():
            raise BackupError(f"A backup named '{final_name}' already exists.")
        plain = directory / f".{final_name}.tmp.db"
        try:
            Backup._snapshot(db_path, plain, conn)
            if require_ok:
                messages = Backup._integrity_messages(plain)
                if messages != ["ok"]:
                    raise BackupError(
                        "Not backing up: the database failed its integrity check "
                        f"({'; '.join(messages)})."
                    )
            Backup._compress(plain, dest)
        except sqlite3.Error as exc:
            raise BackupError(f"Could not back up the database: {exc}") from exc
        finally:
            plain.unlink(missing_ok=True)
        _logger.info("Created database backup %s", dest)
        return Backup._info(dest)

    @staticmethod
    def _info(path: Path) -> BackupInfo:
        stat = path.stat()
        name = path.name[: -len(Backup.SUFFIX)]
        return BackupInfo(
            name=name,
            path=path,
            size=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            kind=Backup._kind(name),
        )

    @staticmethod
    def entries(db_path: Path) -> list[BackupInfo]:
        """Every backup, newest first."""
        directory = Paths.backups_dir(db_path, create=False)
        if not directory.is_dir():
            return []
        infos = [
            Backup._info(path)
            for path in directory.glob(f"*{Backup.SUFFIX}")
            if not path.name.startswith(".")
        ]
        return sorted(infos, key=lambda info: info.created_at, reverse=True)

    @staticmethod
    def find(db_path: Path, name_or_path: str) -> Path:
        """Resolve a backup name ('vethuq db backup list') or a file path to a backup file."""
        candidate = Path(name_or_path).expanduser()
        if candidate.is_file():
            return candidate
        by_name = Backup.directory(db_path) / f"{name_or_path}{Backup.SUFFIX}"
        if by_name.is_file():
            return by_name
        raise BackupError(
            f"No backup named '{name_or_path}' (see '{Hints.command('db backup list')}')."
        )

    @staticmethod
    def delete(db_path: Path, name: str) -> None:
        path = Backup.directory(db_path) / f"{name}{Backup.SUFFIX}"
        if not path.is_file():
            raise BackupError(
                f"No backup named '{name}' (see '{Hints.command('db backup list')}')."
            )
        path.unlink()
        _logger.info("Deleted database backup %s", path)

    @staticmethod
    def prune(db_path: Path, retention_days: int) -> int:
        """Delete automatic/safety backups older than `retention_days`; returns how many.

        The newest `MIN_KEPT` of them are always kept, and user-named snapshots are
        never touched.
        """
        prunable = [info for info in Backup.entries(db_path) if info.kind != "manual"]
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        removed = 0
        for info in prunable[Backup.MIN_KEPT :]:
            if info.created_at < cutoff:
                info.path.unlink(missing_ok=True)
                removed += 1
        if removed:
            _logger.info("Pruned %d old database backup(s)", removed)
        return removed

    @staticmethod
    def move_directory(db_path: Path, target: Path) -> int:
        """Move every backup to `target` and use it from now on; returns how many moved.

        Raises `BackupError` if `target` is the current folder or can't be written to.
        Backups are copied first and only removed once all copies exist.
        """
        current = Backup.directory(db_path)
        if target.resolve() == current.resolve():
            raise BackupError("That is already the backups location.")
        moved: list[Path] = []
        try:
            target.mkdir(parents=True, exist_ok=True)
            for info in Backup.entries(db_path):
                shutil.copy2(info.path, target / info.path.name)
                moved.append(info.path)
        except OSError as exc:
            raise BackupError(f"Could not use '{target}' for backups: {exc}") from exc
        Paths.save_backups_location(target)
        for path in moved:
            path.unlink(missing_ok=True)
        _logger.info("Moved %d database backup(s) to %s", len(moved), target)
        return len(moved)

    @staticmethod
    def reset_directory(db_path: Path) -> int:
        """Move backups back to the default `db/backups` folder; returns how many moved."""
        if Paths.configured_backups_location() is None:
            return 0
        moved = Backup.move_directory(db_path, db_path.parent / Paths.BACKUPS_DIRNAME)
        Paths.clear_backups_location()
        return moved

    @staticmethod
    def maybe_run_auto(storage: Storage, db_path: Path) -> BackupInfo | None:
        """Take an automatic backup on connect if `db_backup` calls for one now.

        Never raises: a failed backup is logged, not allowed to stop the database
        from opening. A database that fails its integrity check is not backed up.
        """
        try:
            if DbSettings.get_backup(storage) == "disable":
                return None
            last_run_at = Settings.get(storage, Backup.LAST_RUN_AT_KEY)
            if last_run_at is not None:
                interval = DbSettings.get_backup_interval_minutes(storage)
                elapsed = datetime.now(UTC) - datetime.fromisoformat(last_run_at)
                if elapsed < timedelta(minutes=interval):
                    return None
            storage.commit()  # let pending writes land so the backup includes them
            info = Backup.create(db_path, prefix=Backup.AUTO_PREFIX)
            Settings.set(storage, Backup.LAST_RUN_AT_KEY, datetime.now(UTC).isoformat())
            Backup.prune(db_path, DbSettings.get_backup_retention_days(storage))
            return info
        except Exception:  # noqa: BLE001 - a failed backup must never block opening the database
            _logger.exception("Automatic database backup failed")
            return None

    @staticmethod
    def _safety_snapshot(db_path: Path) -> BackupInfo | None:
        """Back up the current database before changing it (best effort, no integrity gate)."""
        if not db_path.exists():
            return None
        try:
            return Backup.create(db_path, prefix=Backup.SAFETY_PREFIX, require_ok=False)
        except BackupError as exc:
            raise BackupError(f"Could not take a safety backup first: {exc}") from exc

    @staticmethod
    def _remove_db_files(db_path: Path) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _overwrite_in_place(db_path: Path, source: sqlite3.Connection) -> None:
        """Copy `source` over the live database with SQLite's backup API.

        Used when the database files can't be swapped because another process (the
        desktop app, another command) has them open - SQLite only needs a brief lock.
        """
        live = sqlite3.connect(db_path, timeout=5)
        try:
            source.backup(live)
        except sqlite3.Error as exc:
            raise BackupError(
                f"The database is in use by another VethuQ process ({exc}). "
                "Close the desktop app and any running VethuQ commands, then try again."
            ) from exc
        finally:
            live.close()

    @staticmethod
    def _replace_db(db_path: Path, staged: Path | None) -> None:
        """Make `staged` (or, if None, an empty database) the database at `db_path`.

        Swaps the files when it can; if another process holds them open, overwrites the
        live database in place instead.
        """
        try:
            Backup._remove_db_files(db_path)
            if staged is not None:
                staged.replace(db_path)
            return
        except OSError:
            _logger.warning("Database files are in use; overwriting the live database in place")
        source = sqlite3.connect(staged if staged is not None else ":memory:")
        try:
            Backup._overwrite_in_place(db_path, source)
        finally:
            source.close()

    @staticmethod
    def restore(db_path: Path, name_or_path: str) -> BackupInfo | None:
        """Replace the database with a backup. Returns the safety backup of what it replaced.

        The backup is unpacked and verified (intact, and not from a newer VethuQ)
        before anything is touched. The caller must make sure no index run is active
        and nothing else has the database open.
        """
        source = Backup.find(db_path, name_or_path)
        staging = Backup.directory(db_path) / f".restore-{Backup._timestamp()}.tmp.db"
        try:
            try:
                if source.name.endswith(".gz"):
                    with gzip.open(source, "rb") as src, staging.open("wb") as out:
                        shutil.copyfileobj(src, out)
                else:
                    shutil.copyfile(source, staging)
            except (OSError, EOFError) as exc:
                raise BackupError(f"Could not read the backup '{source}': {exc}") from exc
            messages = Backup._integrity_messages(staging)
            if messages != ["ok"]:
                raise BackupError(
                    f"The backup '{source}' is damaged ({'; '.join(messages)}); "
                    "the database was not changed."
                )
            version = Backup._schema_version(staging)
            if version is not None and version > Db.SCHEMA_VERSION:
                raise BackupError(
                    f"The backup '{source}' comes from a newer version of VethuQ "
                    f"(schema {version}); upgrade VethuQ to restore it."
                )
            safety = Backup._safety_snapshot(db_path)
            Backup._replace_db(db_path, staging)
            Semantic.discard(db_path)
        finally:
            staging.unlink(missing_ok=True)
        _logger.info("Restored database from %s", source)
        return safety

    @staticmethod
    def reset(db_path: Path) -> BackupInfo | None:
        """Delete the database and everything in it (a fresh one is created on next use).

        Returns the safety backup taken first. The caller must make sure no index run
        is active and nothing else has the database open.
        """
        safety = Backup._safety_snapshot(db_path)
        Backup._replace_db(db_path, None)
        Semantic.discard(db_path)
        _logger.info("Reset the database (all data cleared)")
        return safety

    @staticmethod
    def repair(db_path: Path) -> tuple[IntegrityCheckResult, BackupInfo | None]:
        """Rebuild the database's indexes (`REINDEX`) and re-check it.

        Fixes index-only corruption. Anything else still fails the check, and the
        result says so; the safety backup taken first is returned too.
        """
        if not db_path.exists():
            raise BackupError("There is no database to repair yet.")
        safety = Backup._safety_snapshot(db_path)
        conn = sqlite3.connect(db_path)
        try:
            try:
                conn.execute("REINDEX")
                conn.commit()
            except sqlite3.DatabaseError as exc:
                _logger.error("REINDEX failed: %s", exc)
            messages = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        except sqlite3.DatabaseError as exc:
            messages = [str(exc)]
        finally:
            conn.close()
        ok = messages == ["ok"]
        if ok:
            _logger.info("Database repaired: integrity check passes after REINDEX")
        else:
            _logger.error("Database repair did not fix it: %s", "; ".join(messages))
        return IntegrityCheckResult(ok=ok, errors=[] if ok else messages), safety
