from test_noise_index import _add_document, _pdf_row
from vethuq_core.db import Db
from vethuq_core.db.queries.documents import Document
from vethuq_core.db.queries.ocr import Ocr
from vethuq_core.search.normalizers import Normalizers

DECOMPOSED_CAFE = "café"  # an e and a combining accent


def _phrase(word):
    return '"' + Normalizers.index_form(word) + '"'


def _match(conn, table, expression):
    return [
        row[0]
        for row in conn.execute(
            f"SELECT rowid FROM {table}_norm WHERE {table}_norm MATCH ?", (expression,)
        )
    ]


def _check(conn, table):
    conn.execute(f"INSERT INTO {table}_norm({table}_norm) VALUES ('integrity-check')")


class TestNormText:
    def test_the_columns_exist_and_default_to_empty(self, conn):
        for table in ("pdf_pages", "image_pages"):
            columns = {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})")}
            assert columns["norm_text"]["notnull"] == 1
            assert columns["norm_text"]["dflt_value"] == "''"

    def test_pages_are_written_with_their_normalized_text(self, conn):
        pdf_id = _add_document(conn)
        image_id = _add_document(conn, "image", "/docs/a.png")

        Document.insert_pdf_pages(conn, [_pdf_row(pdf_id, 1, f"A {DECOMPOSED_CAFE} h3ll0")])
        Document.insert_image_page(
            conn, image_id, "Ｆｉｎｅ", 4, 0.9, None, None, None, None, 1, "0"
        )

        pdf_text = conn.execute("SELECT norm_text FROM pdf_pages").fetchone()[0]
        assert pdf_text == Normalizers.index_form(f"A {DECOMPOSED_CAFE} h3ll0")
        assert pdf_text.startswith("a cafe he")
        assert conn.execute("SELECT norm_text FROM image_pages").fetchone()[0] == "fine"

    def test_updated_text_gets_new_normalized_text(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "first words")])
        page_id = conn.execute("SELECT id FROM pdf_pages").fetchone()[0]

        Ocr.Page.update_text(conn, "pdf_pages", page_id, "Café again", 0.8, 2, "0,90")

        assert conn.execute("SELECT norm_text FROM pdf_pages").fetchone()[0] == "cafe again"
        assert _match(conn, "pdf_pages", _phrase("cafe")) == [page_id]
        assert _match(conn, "pdf_pages", _phrase("first")) == []
        _check(conn, "pdf_pages")


class TestNormIndex:
    def test_the_index_follows_the_pages(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "Café ﬁne")])
        (page_id,) = [r[0] for r in conn.execute("SELECT id FROM pdf_pages")]

        assert _match(conn, "pdf_pages", _phrase("cafe")) == [page_id]
        assert _match(conn, "pdf_pages", _phrase("fine")) == [page_id]
        conn.execute("DELETE FROM pdf_pages")
        assert _match(conn, "pdf_pages", _phrase("cafe")) == []
        _check(conn, "pdf_pages")

    def test_the_norm_indexes_are_rebuildable_search_indexes(self):
        assert {"pdf_pages_norm", "image_pages_norm"} <= set(Document.SEARCH_INDEXES)

    def test_rebuilding_refreshes_stale_text_and_the_index(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "a Café")])
        conn.execute("UPDATE pdf_pages SET norm_text = ''")
        conn.execute("INSERT INTO pdf_pages_norm(pdf_pages_norm) VALUES ('delete-all')")

        Document.rebuild_search_index(conn, "pdf_pages_norm")

        assert conn.execute("SELECT norm_text FROM pdf_pages").fetchone()[0] == "a cafe"
        assert len(_match(conn, "pdf_pages", _phrase("cafe"))) == 1
        _check(conn, "pdf_pages")

    def test_candidate_queries_narrow_through_the_index(self, conn, storage):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(
            conn,
            [
                _pdf_row(document_id, 1, f"a {DECOMPOSED_CAFE} today"),
                _pdf_row(document_id, 2, "something else entirely"),
            ],
        )

        everything = storage.search_norm_candidate_pdf_pages(None)
        narrowed = storage.search_norm_candidate_pdf_pages(_phrase("cafe"))

        assert [r["page_number"] for r in everything] == [1, 2]
        assert [r["page_number"] for r in narrowed] == [1]
        assert narrowed[0]["ocr_text"] == f"a {DECOMPOSED_CAFE} today"

    def test_candidate_queries_always_include_pages_without_normalized_text(self, conn, storage):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "a cafe")])
        conn.execute("UPDATE pdf_pages SET norm_text = ''")

        assert len(storage.search_norm_candidate_pdf_pages('"zzzzz"')) == 1

    def test_candidate_queries_skip_documents_that_are_not_indexed(self, conn, storage):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "a cafe")])
        conn.execute("UPDATE document_index SET status = 'error'")

        assert storage.search_norm_candidate_pdf_pages(None) == []
        assert storage.search_norm_candidate_image_pages(None) == []


class TestMigration:
    @staticmethod
    def _seed_v29(db_path):
        """A v29 database: pages without `norm_text`, and no norm indexes or triggers."""
        conn = Db.connect(db_path)
        conn.executescript(
            f"""
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/docs', 'folder', 'indexed', '2024-01-01');
            INSERT INTO documents (created_at) VALUES ('2024-01-01'), ('2024-01-01');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/a.pdf', 'pdf', 'indexed'),
                       (2, 1, 2, '/b.png', 'image', 'indexed');
            INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence)
                VALUES (1, 1, 'a {DECOMPOSED_CAFE} here', 0.9), (1, 2, 'Ｆｉｎｅ', 0.9);
            INSERT INTO image_pages (document_id, ocr_text, confidence)
                VALUES (2, 'résumé', 0.9);
            """
        )
        for table in ("pdf_pages", "image_pages"):
            for suffix in ("ai", "ad", "au"):
                conn.execute(f"DROP TRIGGER {table}_norm_{suffix}")
            conn.execute(f"DROP TABLE {table}_norm")
            conn.execute(f"ALTER TABLE {table} DROP COLUMN norm_text")
        conn.execute("UPDATE schema_version SET version = 29")
        conn.commit()
        conn.close()

    def test_adds_and_backfills_the_text_and_builds_the_index(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v29(db_path)

        conn = Db.connect(db_path)
        try:
            texts = [r[0] for r in conn.execute("SELECT norm_text FROM pdf_pages ORDER BY id")]
            assert texts == ["a cafe here", "fine"]
            assert conn.execute("SELECT norm_text FROM image_pages").fetchone()[0] == "resume"
            assert len(_match(conn, "pdf_pages", _phrase("cafe"))) == 1
            assert len(_match(conn, "image_pages", _phrase("resume"))) == 1
            _check(conn, "pdf_pages")
            _check(conn, "image_pages")
            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_every_trigger_is_back(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v29(db_path)

        conn = Db.connect(db_path)
        try:
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            }
            for table in ("pdf_pages", "image_pages"):
                for kind in ("trigram", "words", "noise", "norm"):
                    for suffix in ("ai", "ad", "au"):
                        assert f"{table}_{kind}_{suffix}" in names
            for index in ("pdf_pages_trigram", "pdf_pages_words", "pdf_pages_noise"):
                conn.execute(f"INSERT INTO {index}({index}) VALUES ('integrity-check')")
        finally:
            conn.close()

    def test_a_fresh_database_is_at_the_current_version(self, tmp_path):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            assert {"pdf_pages_norm", "image_pages_norm"} <= tables
            assert Db.SCHEMA_VERSION == 31
        finally:
            conn.close()
