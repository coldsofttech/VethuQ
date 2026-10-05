"""SQL for the semantic search index: one embedding per chunk of a page's text.

The embeddings live in their own SQLite file, `<database name>.semantic.db` beside the main
database, attached to every connection as the schema `semantic`. They are derived data - every
vector can be recomputed from the page text - and large, so keeping them out of the main file
keeps it small, keeps them out of its backups, and lets the whole store be thrown away (damaged,
from a newer VethuQ, or for another database) without touching anything that cannot be
recomputed.

Three things keep a vector from ever describing the wrong text:

* **Versions.** Each embedded page records the `version` it was embedded with (the model's
  name, and a version key covering how text is cut and prepared - see
  `vethuq_core.semantic.SemanticIndex.version`). Pages of another version are never searched;
  they are dropped and embedded again by the next sync. The file itself has a layout version
  (`STORE_VERSION`), and a file of any other layout is recreated.
* **Changed text.** Triggers on the page tables cannot write to the attached file, so they
  queue the page in `semantic_dirty` (in the main database) when its text is rewritten or the
  page is deleted; the queue is applied to the store before it is next read.
* **Identity.** The store records the id of the database it was built for (`database_id` in
  the main `database_identity`). Page ids are only meaningful inside one database, so a store built
  for another one (a reset, a restore) is emptied rather than trusted.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path

_logger = logging.getLogger(__name__)


class Semantic:
    PAGE_KINDS = {"pdf": "pdf_pages", "image": "image_pages"}

    # The attached store's schema name, its file's layout version and its identity key.
    SCHEMA = "semantic"
    STORE_VERSION = 1
    ID_KEY = "database_id"

    @staticmethod
    def path_for(db_path: Path) -> Path:
        """Where the embeddings of the database at `db_path` are kept."""
        return db_path.with_name(f"{db_path.stem}.semantic.db")

    @staticmethod
    def _files(store: Path) -> list[Path]:
        return [Path(f"{store}{suffix}") for suffix in ("", "-wal", "-shm")]

    # ------------------------------------------------------------------ main database

    @staticmethod
    def main_schema() -> str:
        """The queue of pages whose embeddings are stale, and the triggers that fill it.

        Lives in the main database, because that is where the page tables are. A page that is
        deleted or whose text changes is queued; embeddings are dropped from the store when the
        queue is applied (`apply_dirty`).
        """
        statements = [
            # What an earlier build kept inside the main database; the store replaced it.
            "DROP TABLE IF EXISTS main.semantic_chunks",
            "DROP TABLE IF EXISTS main.semantic_pages",
            "DELETE FROM main.settings WHERE key = 'database_id'",
            "CREATE TABLE IF NOT EXISTS database_identity (id TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS semantic_dirty ("
            "kind TEXT NOT NULL CHECK (kind IN ('pdf', 'image')), "
            "page_id INTEGER NOT NULL, "
            "PRIMARY KEY (kind, page_id))",
        ]
        for kind, table in Semantic.PAGE_KINDS.items():
            queue = (
                "INSERT OR IGNORE INTO semantic_dirty (kind, page_id) "
                f"VALUES ('{kind}', old.id); END"
            )
            statements += [
                f"DROP TRIGGER IF EXISTS {table}_semantic_ad",
                f"DROP TRIGGER IF EXISTS {table}_semantic_au",
                f"CREATE TRIGGER IF NOT EXISTS {table}_semantic_dirty_ad "
                f"AFTER DELETE ON {table} BEGIN " + queue,
                f"CREATE TRIGGER IF NOT EXISTS {table}_semantic_dirty_au "
                f"AFTER UPDATE OF ocr_text ON {table} WHEN old.ocr_text != new.ocr_text BEGIN "
                + queue,
            ]
        return ";\n".join(statements) + ";\n"

    @staticmethod
    def _database_id(conn: sqlite3.Connection) -> str:
        """The id of the main database, created on first use."""
        row = conn.execute("SELECT id FROM main.database_identity LIMIT 1").fetchone()
        if row is not None:
            return row[0]
        conn.execute("INSERT INTO main.database_identity (id) VALUES (?)", (uuid.uuid4().hex,))
        conn.commit()
        return conn.execute("SELECT id FROM main.database_identity LIMIT 1").fetchone()[0]

    # ------------------------------------------------------------------ the store

    @staticmethod
    def _store_schema() -> str:
        schema = Semantic.SCHEMA
        return (
            f"CREATE TABLE IF NOT EXISTS {schema}.meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL);\n"
            f"CREATE TABLE IF NOT EXISTS {schema}.pages ("
            "kind TEXT NOT NULL CHECK (kind IN ('pdf', 'image')), "
            "page_id INTEGER NOT NULL, "
            "model TEXT NOT NULL, "
            "version TEXT NOT NULL, "
            "chunk_count INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (kind, page_id, model));\n"
            f"CREATE TABLE IF NOT EXISTS {schema}.chunks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "kind TEXT NOT NULL CHECK (kind IN ('pdf', 'image')), "
            "page_id INTEGER NOT NULL, "
            "model TEXT NOT NULL, "
            "chunk_index INTEGER NOT NULL, "
            "start_char INTEGER NOT NULL, "
            "end_char INTEGER NOT NULL, "
            "vector BLOB NOT NULL);\n"
            f"CREATE INDEX IF NOT EXISTS {schema}.chunks_page "
            "ON chunks (kind, page_id, model);\n"
        )

    @staticmethod
    def _open_store(conn: sqlite3.Connection, store: Path) -> None:
        conn.execute(f"ATTACH DATABASE ? AS {Semantic.SCHEMA}", (str(store),))
        conn.execute(f"PRAGMA {Semantic.SCHEMA}.journal_mode = WAL")
        conn.executescript(Semantic._store_schema())

    @staticmethod
    def _detach(conn: sqlite3.Connection) -> None:
        conn.commit()
        try:
            conn.execute(f"DETACH DATABASE {Semantic.SCHEMA}")
        except sqlite3.Error:
            pass

    @staticmethod
    def _wipe(conn: sqlite3.Connection) -> None:
        conn.execute(f"DELETE FROM {Semantic.SCHEMA}.chunks")
        conn.execute(f"DELETE FROM {Semantic.SCHEMA}.pages")
        conn.execute("DELETE FROM main.semantic_dirty")

    @staticmethod
    def attach(conn: sqlite3.Connection, db_path: Path) -> None:
        """Attach the embedding store of the database at `db_path` as the schema `semantic`.

        A store that is damaged is recreated, one of another layout or built for another
        database is emptied: it only ever holds what can be computed again.
        """
        store = Semantic.path_for(db_path)
        conn.commit()
        for attempt in (1, 2):
            try:
                Semantic._open_store(conn, store)
                break
            except sqlite3.DatabaseError as exc:
                if attempt == 2:
                    raise
                _logger.warning("Semantic store %s is unusable (%s); recreating it", store, exc)
                Semantic._detach(conn)
                for path in Semantic._files(store):
                    path.unlink(missing_ok=True)
        meta = dict(conn.execute(f"SELECT key, value FROM {Semantic.SCHEMA}.meta").fetchall())
        identity = Semantic._database_id(conn)
        layout = str(Semantic.STORE_VERSION)
        if meta.get("layout") != layout or meta.get(Semantic.ID_KEY) != identity:
            if meta:
                _logger.info("Semantic store does not belong to this database; emptying it")
            Semantic._wipe(conn)
            conn.executemany(
                f"INSERT OR REPLACE INTO {Semantic.SCHEMA}.meta (key, value) VALUES (?, ?)",
                [("layout", layout), (Semantic.ID_KEY, identity)],
            )
        elif not conn.execute(f"SELECT 1 FROM {Semantic.SCHEMA}.pages LIMIT 1").fetchone():
            # Nothing is embedded, so nothing the queue could be about.
            conn.execute("DELETE FROM main.semantic_dirty")
        conn.commit()

    @staticmethod
    def store_file(conn: sqlite3.Connection) -> Path | None:
        """The attached store's file, or None if it is not attached."""
        for row in conn.execute("PRAGMA database_list").fetchall():
            if row[1] == Semantic.SCHEMA and row[2]:
                return Path(row[2])
        return None

    @staticmethod
    def discard(db_path: Path) -> None:
        """Delete the embedding store of the database at `db_path` (it is recreated, empty, the
        next time that database is opened) and make any copy still open forget what it held.

        For when the database's content is replaced - a reset or a restore - so page ids that
        now mean something else can't pick up the old vectors. Best effort: a file another
        process holds open is emptied by that identity change instead.
        """
        for path in Semantic._files(Semantic.path_for(db_path)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _logger.warning("Could not delete %s; the store will be emptied instead", path)
        if not db_path.exists():
            return
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE database_identity SET id = ?", (uuid.uuid4().hex,))
            conn.commit()
        except sqlite3.Error:
            pass  # no identity table yet: nothing carries an identity
        finally:
            conn.close()

    # ------------------------------------------------------------------ reading and writing

    @staticmethod
    def apply_dirty(conn: sqlite3.Connection) -> int:
        """Drop the embeddings of every queued page, then empty the queue. Returns pages dropped."""
        schema = Semantic.SCHEMA
        queued = (
            "EXISTS (SELECT 1 FROM main.semantic_dirty d "
            "WHERE d.kind = {t}.kind AND d.page_id = {t}.page_id)"
        )
        conn.execute(f"DELETE FROM {schema}.chunks WHERE " + queued.format(t="chunks"))
        dropped = conn.execute(
            f"DELETE FROM {schema}.pages WHERE " + queued.format(t="pages")
        ).rowcount
        conn.execute("DELETE FROM main.semantic_dirty")
        # Always: the DELETEs above opened a write transaction even if they matched nothing, and
        # one left open blocks a backup of the database taken through this connection.
        conn.commit()
        return dropped

    @staticmethod
    def purge_stale(conn: sqlite3.Connection, model: str, version: str) -> int:
        """Drop `model`'s embeddings made with another `version`. Returns pages dropped."""
        schema = Semantic.SCHEMA
        conn.execute(
            f"DELETE FROM {schema}.chunks WHERE model = ? AND EXISTS ("
            f"SELECT 1 FROM {schema}.pages sp WHERE sp.kind = chunks.kind "
            "AND sp.page_id = chunks.page_id AND sp.model = chunks.model AND sp.version != ?)",
            (model, version),
        )
        dropped = conn.execute(
            f"DELETE FROM {schema}.pages WHERE model = ? AND version != ?", (model, version)
        ).rowcount
        conn.commit()
        return dropped

    @staticmethod
    def _searchable(kind: str, page: str = "p") -> str:
        """SQL: the page `page` of `kind` belongs to a file that is indexed and in an active
        source - what every search engine reads, duplicates of a carrier included."""
        return (
            "EXISTS (SELECT 1 FROM main.document_index carrier "
            "JOIN main.document_index di ON di.document_id = carrier.document_id "
            "JOIN main.sources s ON s.id = di.source_id "
            f"WHERE carrier.id = {page}.document_id "
            "AND (di.status = 'indexed' OR di.reindex_pending) "
            f"AND s.is_active = 1 AND di.file_type = '{kind}')"
        )

    @staticmethod
    def list_unembedded_pages(
        conn: sqlite3.Connection, model: str, version: str, limit: int
    ) -> list[sqlite3.Row]:
        """Searchable pages `model` has not embedded at `version` yet (`kind`, `page_id`,
        `ocr_text`), PDF pages first, at most `limit`."""
        Semantic.apply_dirty(conn)
        rows: list[sqlite3.Row] = []
        for kind, table in Semantic.PAGE_KINDS.items():
            rows.extend(
                conn.execute(
                    f"SELECT '{kind}' AS kind, p.id AS page_id, p.ocr_text AS ocr_text "
                    f"FROM main.{table} p "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {Semantic.SCHEMA}.pages sp "
                    f"WHERE sp.kind = '{kind}' AND sp.page_id = p.id AND sp.model = ? "
                    "AND sp.version = ?) "
                    f"AND {Semantic._searchable(kind)} "
                    "ORDER BY p.id LIMIT ?",
                    (model, version, limit - len(rows)),
                ).fetchall()
            )
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def count(conn: sqlite3.Connection, model: str, version: str) -> dict[str, int]:
        """How much of the searchable text `model` has embedded at `version`: `pages` that are
        searchable, `embedded` of them, the `chunks` held for them, and `stale` pages embedded
        with another version (they are embedded again by the next sync)."""
        Semantic.apply_dirty(conn)
        schema = Semantic.SCHEMA
        pages = embedded = chunks = 0
        for kind, table in Semantic.PAGE_KINDS.items():
            searchable = Semantic._searchable(kind)
            pages += conn.execute(
                f"SELECT COUNT(*) FROM main.{table} p WHERE {searchable}"
            ).fetchone()[0]
            embedded += conn.execute(
                f"SELECT COUNT(*) FROM main.{table} p WHERE {searchable} AND EXISTS ("
                f"SELECT 1 FROM {schema}.pages sp "
                f"WHERE sp.kind = '{kind}' AND sp.page_id = p.id AND sp.model = ? "
                "AND sp.version = ?)",
                (model, version),
            ).fetchone()[0]
            chunks += conn.execute(
                f"SELECT COUNT(*) FROM {schema}.chunks sc "
                f"WHERE sc.kind = '{kind}' AND sc.model = ? AND EXISTS ("
                f"SELECT 1 FROM {schema}.pages sp WHERE sp.kind = sc.kind "
                "AND sp.page_id = sc.page_id AND sp.model = sc.model AND sp.version = ?) "
                f"AND EXISTS (SELECT 1 FROM main.{table} p WHERE p.id = sc.page_id "
                f"AND {searchable})",
                (model, version),
            ).fetchone()[0]
        stale = conn.execute(
            f"SELECT COUNT(*) FROM {schema}.pages WHERE model = ? AND version != ?",
            (model, version),
        ).fetchone()[0]
        return {"pages": pages, "embedded": embedded, "chunks": chunks, "stale": stale}

    @staticmethod
    def replace_page(
        conn: sqlite3.Connection,
        kind: str,
        page_id: int,
        model: str,
        version: str,
        chunks: Sequence[tuple[int, int, int, bytes]],
    ) -> None:
        """Record `chunks` - `(index, start, end, vector)` - as the embedding of one page."""
        schema = Semantic.SCHEMA
        conn.execute(
            f"DELETE FROM {schema}.chunks WHERE kind = ? AND page_id = ? AND model = ?",
            (kind, page_id, model),
        )
        conn.executemany(
            f"INSERT INTO {schema}.chunks "
            "(kind, page_id, model, chunk_index, start_char, end_char, vector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(kind, page_id, model, index, start, end, vec) for index, start, end, vec in chunks],
        )
        conn.execute(
            f"INSERT OR REPLACE INTO {schema}.pages (kind, page_id, model, version, chunk_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, page_id, model, version, len(chunks)),
        )

    @staticmethod
    def list_chunks(conn: sqlite3.Connection, model: str, version: str) -> list[sqlite3.Row]:
        """Every chunk of `model` at `version` on a searchable page: `kind`, `page_id`,
        `start_char`, `end_char`, `vector`."""
        Semantic.apply_dirty(conn)
        schema = Semantic.SCHEMA
        rows: list[sqlite3.Row] = []
        for kind, table in Semantic.PAGE_KINDS.items():
            rows.extend(
                conn.execute(
                    "SELECT sc.kind AS kind, sc.page_id AS page_id, "
                    "sc.start_char AS start_char, sc.end_char AS end_char, sc.vector AS vector "
                    f"FROM {schema}.chunks sc "
                    f"WHERE sc.kind = '{kind}' AND sc.model = ? AND EXISTS ("
                    f"SELECT 1 FROM {schema}.pages sp WHERE sp.kind = sc.kind "
                    "AND sp.page_id = sc.page_id AND sp.model = sc.model AND sp.version = ?) "
                    f"AND EXISTS (SELECT 1 FROM main.{table} p WHERE p.id = sc.page_id "
                    f"AND {Semantic._searchable(kind)}) "
                    "ORDER BY sc.page_id, sc.chunk_index",
                    (model, version),
                ).fetchall()
            )
        return rows

    @staticmethod
    def list_page_rows(
        conn: sqlite3.Connection, kind: str, page_ids: Sequence[int]
    ) -> list[sqlite3.Row]:
        """The searchable files holding pages `page_ids` of `kind`, shaped like the other
        engines' candidate rows plus the carrier's `page_id` (a duplicate file is a row of its
        own, reusing the carrier's text)."""
        if not page_ids:
            return []
        table = Semantic.PAGE_KINDS[kind]
        marks = ", ".join("?" for _ in page_ids)
        page_number = "p.page_number" if kind == "pdf" else "NULL"
        source = "p.source" if kind == "pdf" else "'ocr'"
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, p.ocr_text AS ocr_text, "
            f"p.id AS page_id, {page_number} AS page_number, {source} AS source, "
            "carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            f"FROM main.{table} p "
            "JOIN main.document_index carrier ON carrier.id = p.document_id "
            "JOIN main.document_index di ON di.document_id = carrier.document_id "
            "JOIN main.sources s ON s.id = di.source_id "
            f"WHERE p.id IN ({marks}) "
            "AND (di.status = 'indexed' OR di.reindex_pending) "
            f"AND s.is_active = 1 AND di.file_type = '{kind}' "
            "ORDER BY di.file_path",
            tuple(page_ids),
        ).fetchall()

    @staticmethod
    def clear(conn: sqlite3.Connection, model: str | None = None) -> int:
        """Drop every embedding (of `model`, or of all models). Returns the pages dropped.

        Dropping all of them also gives the file's space back."""
        schema = Semantic.SCHEMA
        if model is None:
            conn.execute(f"DELETE FROM {schema}.chunks")
            dropped = conn.execute(f"DELETE FROM {schema}.pages").rowcount
            conn.execute("DELETE FROM main.semantic_dirty")
            conn.commit()
            conn.execute(f"VACUUM {schema}")
            conn.execute(f"PRAGMA {schema}.wal_checkpoint(TRUNCATE)")
            return dropped
        conn.execute(f"DELETE FROM {schema}.chunks WHERE model = ?", (model,))
        return conn.execute(f"DELETE FROM {schema}.pages WHERE model = ?", (model,)).rowcount
