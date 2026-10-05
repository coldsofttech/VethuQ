"""SQL for the semantic search index: one embedding per chunk of a page's text.

`semantic_pages` records which pages have been embedded by which model (a page with no text
has no chunks but is still recorded, so it is not tried again), and `semantic_chunks` holds
each chunk's span in the page's text and its vector, a normalized float32 array stored as a
BLOB. Triggers on the page tables drop a page's rows when the page is deleted or its text is
rewritten, so a stale vector can never outlive the text it describes; the page is then simply
embedded again the next time the index is brought up to date.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence


class Semantic:
    PAGE_KINDS = {"pdf": "pdf_pages", "image": "image_pages"}

    @staticmethod
    def schema() -> str:
        """The semantic tables, their index and the triggers keeping them in step with the pages."""
        statements = [
            "CREATE TABLE IF NOT EXISTS semantic_pages ("
            "kind TEXT NOT NULL CHECK (kind IN ('pdf', 'image')), "
            "page_id INTEGER NOT NULL, "
            "model TEXT NOT NULL, "
            "chunk_count INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (kind, page_id, model))",
            "CREATE TABLE IF NOT EXISTS semantic_chunks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "kind TEXT NOT NULL CHECK (kind IN ('pdf', 'image')), "
            "page_id INTEGER NOT NULL, "
            "model TEXT NOT NULL, "
            "chunk_index INTEGER NOT NULL, "
            "start_char INTEGER NOT NULL, "
            "end_char INTEGER NOT NULL, "
            "vector BLOB NOT NULL)",
            "CREATE INDEX IF NOT EXISTS semantic_chunks_page "
            "ON semantic_chunks (kind, page_id, model)",
        ]
        for kind, table in Semantic.PAGE_KINDS.items():
            drop = (
                f"DELETE FROM semantic_chunks WHERE kind = '{kind}' AND page_id = old.id; "
                f"DELETE FROM semantic_pages WHERE kind = '{kind}' AND page_id = old.id; END"
            )
            statements.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_semantic_ad AFTER DELETE ON {table} BEGIN "
                + drop
            )
            statements.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_semantic_au "
                f"AFTER UPDATE OF ocr_text ON {table} WHEN old.ocr_text != new.ocr_text BEGIN "
                + drop
            )
        return ";\n".join(statements) + ";\n"

    @staticmethod
    def _searchable(kind: str, page: str = "p") -> str:
        """SQL: the page `page` of `kind` belongs to a file that is indexed and in an active
        source - what every search engine reads, duplicates of a carrier included."""
        return (
            "EXISTS (SELECT 1 FROM document_index carrier "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            f"WHERE carrier.id = {page}.document_id "
            "AND (di.status = 'indexed' OR di.reindex_pending) "
            f"AND s.is_active = 1 AND di.file_type = '{kind}')"
        )

    @staticmethod
    def list_unembedded_pages(
        conn: sqlite3.Connection, model: str, limit: int
    ) -> list[sqlite3.Row]:
        """Searchable pages `model` has not embedded yet (`kind`, `page_id`, `ocr_text`), PDF
        pages first, at most `limit`."""
        rows: list[sqlite3.Row] = []
        for kind, table in Semantic.PAGE_KINDS.items():
            rows.extend(
                conn.execute(
                    f"SELECT '{kind}' AS kind, p.id AS page_id, p.ocr_text AS ocr_text "
                    f"FROM {table} p "
                    "WHERE NOT EXISTS (SELECT 1 FROM semantic_pages sp "
                    f"WHERE sp.kind = '{kind}' AND sp.page_id = p.id AND sp.model = ?) "
                    f"AND {Semantic._searchable(kind)} "
                    "ORDER BY p.id LIMIT ?",
                    (model, limit - len(rows)),
                ).fetchall()
            )
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def count(conn: sqlite3.Connection, model: str) -> dict[str, int]:
        """How much of the searchable text `model` has embedded: `pages` that are searchable,
        `embedded` of them, and the `chunks` held for them."""
        pages = embedded = chunks = 0
        for kind, table in Semantic.PAGE_KINDS.items():
            searchable = Semantic._searchable(kind)
            pages += conn.execute(f"SELECT COUNT(*) FROM {table} p WHERE {searchable}").fetchone()[
                0
            ]
            embedded += conn.execute(
                f"SELECT COUNT(*) FROM {table} p WHERE {searchable} AND EXISTS ("
                "SELECT 1 FROM semantic_pages sp "
                f"WHERE sp.kind = '{kind}' AND sp.page_id = p.id AND sp.model = ?)",
                (model,),
            ).fetchone()[0]
            chunks += conn.execute(
                "SELECT COUNT(*) FROM semantic_chunks sc "
                f"WHERE sc.kind = '{kind}' AND sc.model = ? AND EXISTS ("
                f"SELECT 1 FROM {table} p WHERE p.id = sc.page_id AND {searchable})",
                (model,),
            ).fetchone()[0]
        return {"pages": pages, "embedded": embedded, "chunks": chunks}

    @staticmethod
    def replace_page(
        conn: sqlite3.Connection,
        kind: str,
        page_id: int,
        model: str,
        chunks: Sequence[tuple[int, int, int, bytes]],
    ) -> None:
        """Record `chunks` - `(index, start, end, vector)` - as the embedding of one page."""
        conn.execute(
            "DELETE FROM semantic_chunks WHERE kind = ? AND page_id = ? AND model = ?",
            (kind, page_id, model),
        )
        conn.executemany(
            "INSERT INTO semantic_chunks "
            "(kind, page_id, model, chunk_index, start_char, end_char, vector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(kind, page_id, model, index, start, end, vec) for index, start, end, vec in chunks],
        )
        conn.execute(
            "INSERT OR REPLACE INTO semantic_pages (kind, page_id, model, chunk_count) "
            "VALUES (?, ?, ?, ?)",
            (kind, page_id, model, len(chunks)),
        )

    @staticmethod
    def list_chunks(conn: sqlite3.Connection, model: str) -> list[sqlite3.Row]:
        """Every chunk of `model` on a searchable page: `kind`, `page_id`, `start_char`,
        `end_char`, `vector`."""
        rows: list[sqlite3.Row] = []
        for kind, table in Semantic.PAGE_KINDS.items():
            rows.extend(
                conn.execute(
                    "SELECT sc.kind AS kind, sc.page_id AS page_id, "
                    "sc.start_char AS start_char, sc.end_char AS end_char, sc.vector AS vector "
                    "FROM semantic_chunks sc "
                    f"WHERE sc.kind = '{kind}' AND sc.model = ? AND EXISTS ("
                    f"SELECT 1 FROM {table} p WHERE p.id = sc.page_id "
                    f"AND {Semantic._searchable(kind)}) "
                    "ORDER BY sc.page_id, sc.chunk_index",
                    (model,),
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
            f"FROM {table} p "
            "JOIN document_index carrier ON carrier.id = p.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            f"WHERE p.id IN ({marks}) "
            "AND (di.status = 'indexed' OR di.reindex_pending) "
            f"AND s.is_active = 1 AND di.file_type = '{kind}' "
            "ORDER BY di.file_path",
            tuple(page_ids),
        ).fetchall()

    @staticmethod
    def clear(conn: sqlite3.Connection, model: str | None = None) -> int:
        """Drop every embedding (of `model`, or of all models). Returns the pages dropped."""
        if model is None:
            conn.execute("DELETE FROM semantic_chunks")
            return conn.execute("DELETE FROM semantic_pages").rowcount
        conn.execute("DELETE FROM semantic_chunks WHERE model = ?", (model,))
        return conn.execute("DELETE FROM semantic_pages WHERE model = ?", (model,)).rowcount
