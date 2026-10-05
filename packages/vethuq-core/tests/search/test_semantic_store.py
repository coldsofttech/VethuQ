"""Where the embeddings are kept, and what stops them describing text they weren't made from."""

import sqlite3
from pathlib import Path

import pytest
from search_data import SearchData
from vethuq_core.db import Db
from vethuq_core.db.backup import Backup
from vethuq_core.db.queries.semantic import Semantic
from vethuq_core.semantic import Chunker, SemanticIndex
from vethuq_core.storage.sqlite import SqliteStorage


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "vethuq.db"


def _seed(conn, text="Refund policy for customers.", path="/docs/a.pdf"):
    return SearchData.seed_page(conn, text, path)


def _reopen(conn, db_path):
    conn.close()
    reopened = Db.connect(db_path)
    return reopened, SqliteStorage(reopened)


def _tables(path: Path) -> set[str]:
    plain = sqlite3.connect(path)
    try:
        return {r[0] for r in plain.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        plain.close()


class TestSeparateStore:
    def test_the_embeddings_are_in_their_own_file(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)

        store = Semantic.path_for(db_path)
        assert store == db_path.with_name("vethuq.semantic.db")
        assert store.exists()
        assert {"chunks", "pages", "meta"} <= _tables(store)
        assert not {"chunks", "pages", "semantic_chunks", "semantic_pages"} & _tables(db_path)
        assert storage.semantic_store_path() == store

    def test_the_main_database_holds_no_vectors_and_neither_do_its_backups(
        self, conn, storage, embedder, db_path, tmp_path
    ):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        snapshot = tmp_path / "snapshot.db"

        Backup._snapshot(db_path, snapshot, conn)

        names = _tables(snapshot)
        assert "pdf_pages" in names
        assert not {"chunks", "pages", "semantic_chunks", "semantic_pages"} & names

    def test_the_embeddings_survive_reopening_the_database(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)

        conn, storage = _reopen(conn, db_path)

        assert SemanticIndex.status(storage, embedder.model).embedded == 1

    def test_status_says_where_the_store_is_and_how_big(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)

        status = SemanticIndex.status(storage, embedder.model)

        assert status.path == Semantic.path_for(db_path)
        assert status.size_bytes > 0

    def test_a_store_an_earlier_build_kept_in_the_main_database_is_dropped(self, conn, db_path):
        conn.execute("CREATE TABLE semantic_chunks (id INTEGER)")
        conn.execute("CREATE TABLE semantic_pages (id INTEGER)")
        conn.execute(
            "CREATE TRIGGER pdf_pages_semantic_ad AFTER DELETE ON pdf_pages "
            "BEGIN DELETE FROM semantic_chunks; END"
        )
        conn.commit()

        conn, _ = _reopen(conn, db_path)

        names = _tables(db_path)
        assert "semantic_chunks" not in names and "semantic_pages" not in names
        # ...and deleting a page no longer runs the old trigger against a missing table.
        _seed(conn)
        conn.execute("DELETE FROM pdf_pages")
        conn.commit()


class TestVersions:
    def test_a_new_version_makes_every_page_stale_until_embedded_again(
        self, conn, storage, embedder, monkeypatch
    ):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        monkeypatch.setattr(SemanticIndex, "VERSION", SemanticIndex.VERSION + 1)

        status = SemanticIndex.status(storage, embedder.model)

        assert (status.embedded, status.pending, status.stale) == (0, 1, 1)
        assert storage.list_semantic_chunks(embedder.model, SemanticIndex.version()) == []

        result = SemanticIndex.sync(storage, embedder)

        after = SemanticIndex.status(storage, embedder.model)
        assert result.pages == 1
        assert (after.embedded, after.stale, after.chunks) == (1, 0, 1)
        assert conn.execute("SELECT COUNT(*) FROM semantic.chunks").fetchone()[0] == 1
        assert conn.execute("SELECT DISTINCT version FROM semantic.pages").fetchall()[0][0] == (
            SemanticIndex.version()
        )

    def test_the_chunk_size_is_part_of_the_version(self, monkeypatch):
        before = SemanticIndex.version()
        monkeypatch.setattr(Chunker, "MAX_CHARS", Chunker.MAX_CHARS + 100)
        assert SemanticIndex.version() != before

    def test_the_version_reads_as_format_and_chunk_size(self):
        assert SemanticIndex.version() == f"{SemanticIndex.VERSION}/{Chunker.MAX_CHARS}"

    def test_stale_vectors_are_never_searched(self, conn, storage, embedder, monkeypatch):
        from vethuq_core.search import Search

        _seed(conn, "Customers may get a full reimbursement.")
        assert Search.indexed_content(storage, "refund", engine="semantic", threshold=0.2)
        monkeypatch.setattr(SemanticIndex, "VERSION", SemanticIndex.VERSION + 1)
        embedded = len(embedder.passages)

        # The search brings the index up to the new version first, so it still finds the page.
        assert Search.indexed_content(storage, "refund", engine="semantic", threshold=0.2)
        assert len(embedder.passages) == embedded + 1

    def test_models_are_versioned_separately_from_each_other(
        self, conn, storage, embedder, monkeypatch
    ):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)

        class Other(type(embedder)):
            model = "other-model"

        SemanticIndex.sync(storage, Other())
        monkeypatch.setattr(SemanticIndex, "VERSION", SemanticIndex.VERSION + 1)
        SemanticIndex.sync(storage, embedder)

        # Bringing one model up to date does not touch the other's older vectors.
        assert SemanticIndex.status(storage, "other-model").stale == 1
        assert SemanticIndex.status(storage, embedder.model).stale == 0


class TestChangedText:
    def test_the_queue_of_changed_pages_is_applied_before_reading(self, conn, storage, embedder):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)

        conn.execute("UPDATE pdf_pages SET ocr_text = 'A different text about a museum.'")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM semantic_dirty").fetchone()[0] == 1

        assert SemanticIndex.status(storage, embedder.model).pending == 1
        assert conn.execute("SELECT COUNT(*) FROM semantic_dirty").fetchone()[0] == 0

    def test_a_queue_nothing_can_use_is_emptied_when_the_database_opens(self, conn, db_path):
        _seed(conn)
        conn.execute("DELETE FROM pdf_pages")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM semantic_dirty").fetchone()[0] == 1

        conn, _ = _reopen(conn, db_path)

        assert conn.execute("SELECT COUNT(*) FROM semantic_dirty").fetchone()[0] == 0


class TestDisposableStore:
    def test_a_damaged_store_is_recreated_not_fatal(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        conn.close()
        Semantic.path_for(db_path).write_bytes(b"this is not a database" * 100)

        conn = Db.connect(db_path)
        storage = SqliteStorage(conn)

        assert SemanticIndex.status(storage, embedder.model).embedded == 0
        assert SemanticIndex.sync(storage, embedder).pages == 1

    def test_a_store_of_another_layout_is_emptied(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        conn.execute("UPDATE semantic.meta SET value = '99' WHERE key = 'layout'")
        conn.commit()

        conn, storage = _reopen(conn, db_path)

        assert SemanticIndex.status(storage, embedder.model).embedded == 0
        assert conn.execute("SELECT value FROM semantic.meta WHERE key='layout'").fetchone()[
            0
        ] == str(Semantic.STORE_VERSION)

    def test_a_store_built_for_another_database_is_emptied(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        conn.execute("UPDATE database_identity SET id = 'someone-else'")
        conn.commit()

        conn, storage = _reopen(conn, db_path)

        assert SemanticIndex.status(storage, embedder.model).embedded == 0

    def test_the_same_database_keeps_its_store(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        identity = conn.execute("SELECT id FROM database_identity").fetchone()[0]

        conn, storage = _reopen(conn, db_path)

        assert conn.execute("SELECT id FROM database_identity").fetchone()[0] == identity
        assert SemanticIndex.status(storage, embedder.model).embedded == 1

    def test_reset_discards_the_store(self, conn, storage, embedder, db_path):
        _seed(conn)
        SemanticIndex.sync(storage, embedder)
        conn.close()
        assert Semantic.path_for(db_path).exists()

        Backup.reset(db_path)

        assert not Semantic.path_for(db_path).exists()

    def test_restore_discards_the_store_and_changes_the_identity(
        self, conn, storage, embedder, db_path
    ):
        _seed(conn)
        backup = Backup.create(db_path, "before")
        SemanticIndex.sync(storage, embedder)
        before = conn.execute("SELECT id FROM database_identity").fetchone()[0]
        conn.close()

        Backup.restore(db_path, backup.name)

        assert not Semantic.path_for(db_path).exists()
        plain = sqlite3.connect(db_path)
        try:
            after = plain.execute("SELECT id FROM database_identity").fetchone()
        finally:
            plain.close()
        assert after is None or after[0] != before
        reopened = Db.connect(db_path)
        try:
            assert SemanticIndex.status(SqliteStorage(reopened), embedder.model).embedded == 0
        finally:
            reopened.close()

    def test_clear_empties_the_store_and_gives_the_space_back(self, conn, storage, embedder):
        for number in range(20):
            _seed(conn, "Refund policy. " * 50, f"/docs/{number}.pdf")
        SemanticIndex.sync(storage, embedder)
        grown = SemanticIndex.status(storage, embedder.model).size_bytes

        assert SemanticIndex.clear(storage) == 20

        status = SemanticIndex.status(storage, embedder.model)
        assert (status.embedded, status.chunks) == (0, 0)
        assert status.size_bytes < grown
