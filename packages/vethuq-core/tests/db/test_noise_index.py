import sqlite3

import pytest
from vethuq_core.db import Db
from vethuq_core.db.queries.documents import Document
from vethuq_core.db.queries.ocr import Ocr
from vethuq_core.search.normalizers.leetspeak import Leet


def _add_document(conn, file_type="pdf", path="/docs/a.pdf"):
    conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES (?, 'folder', 'indexed', '2026-01-01T00:00:00+00:00')",
        (path + ".src",),
    )
    source_id = conn.execute("SELECT MAX(id) FROM sources").fetchone()[0]
    conn.execute("INSERT INTO documents (created_at) VALUES ('2026-01-01T00:00:00+00:00')")
    logical = conn.execute("SELECT MAX(id) FROM documents").fetchone()[0]
    conn.execute(
        "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
        "VALUES (?, ?, ?, ?, 'indexed')",
        (source_id, logical, path, file_type),
    )
    conn.commit()
    return conn.execute("SELECT MAX(id) FROM document_index").fetchone()[0]


def _pdf_row(document_id, page, text):
    return (document_id, page, text, len(text), 0.9, "ocr", None, None, None, None, 1, "0")


def _phrase(word):
    """`word` as the quoted trigram phrase its skeleton is searched by."""
    return '"' + Leet.skeleton(word) + '"'


def _match(conn, table, expression):
    return [
        row[0]
        for row in conn.execute(
            f"SELECT rowid FROM {table}_noise WHERE {table}_noise MATCH ?", (expression,)
        )
    ]


def _check(conn, table):
    # An external-content FTS5 index that is out of step with its table fails this check.
    conn.execute(f"INSERT INTO {table}_noise({table}_noise) VALUES ('integrity-check')")


class TestNoiseText:
    def test_the_columns_exist_and_default_to_empty(self, conn):
        for table in ("pdf_pages", "image_pages"):
            columns = {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})")}
            assert columns["noise_text"]["notnull"] == 1
            assert columns["noise_text"]["dflt_value"] == "''"

    def test_pdf_pages_are_written_with_their_skeleton(self, conn):
        document_id = _add_document(conn)

        Document.insert_pdf_pages(
            conn, [_pdf_row(document_id, 1, "say h3ll0 now"), _pdf_row(document_id, 2, "...")]
        )

        rows = conn.execute("SELECT page_number, noise_text FROM pdf_pages ORDER BY id").fetchall()
        assert [(r["page_number"], r["noise_text"]) for r in rows] == [
            (1, "sayheiionow"),
            (2, ""),
        ]

    def test_image_pages_are_written_with_their_skeleton(self, conn):
        document_id = _add_document(conn, "image", "/docs/a.png")

        Document.insert_image_page(
            conn, document_id, "p@55w0rd", 8, 0.9, None, None, None, None, 1, "0"
        )

        assert conn.execute("SELECT noise_text FROM image_pages").fetchone()[0] == "password"

    def test_updated_text_gets_a_new_skeleton(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "first words")])
        page_id = conn.execute("SELECT id FROM pdf_pages").fetchone()[0]

        Ocr.Page.update_text(conn, "pdf_pages", page_id, "h3ll0 again", 0.8, 2, "0,90")

        row = conn.execute("SELECT ocr_text, noise_text FROM pdf_pages").fetchone()
        assert (row["ocr_text"], row["noise_text"]) == ("h3ll0 again", Leet.skeleton("h3ll0 again"))
        assert _match(conn, "pdf_pages", '"heiio"') == [page_id]
        assert _match(conn, "pdf_pages", _phrase("first")) == []


class TestNoiseIndex:
    def test_it_is_a_trigram_index_of_the_skeleton(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "say h @ 3 l l 0 now")])
        page_id = conn.execute("SELECT id FROM pdf_pages").fetchone()[0]

        assert _match(conn, "pdf_pages", '"haeiio"') == [page_id]
        assert _match(conn, "pdf_pages", '"aeiio"') == [page_id]  # any part of it
        assert _match(conn, "pdf_pages", '"hello"') == []  # not the raw text, nor an unfolded word

    def test_it_stays_in_step_with_the_pages_table(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "original wording")])
        page_id = conn.execute("SELECT id FROM pdf_pages").fetchone()[0]
        assert _match(conn, "pdf_pages", _phrase("original")) == [page_id]

        conn.execute(
            "UPDATE pdf_pages SET ocr_text = 'revised wording', noise_text = ? WHERE id = ?",
            (Leet.skeleton("revised wording"), page_id),
        )
        assert _match(conn, "pdf_pages", _phrase("original")) == []
        assert _match(conn, "pdf_pages", _phrase("revised")) == [page_id]

        conn.execute("UPDATE pdf_pages SET ocr_phase = 2")  # an unrelated update
        assert _match(conn, "pdf_pages", _phrase("revised")) == [page_id]

        conn.execute("DELETE FROM pdf_pages")
        assert _match(conn, "pdf_pages", _phrase("revised")) == []
        _check(conn, "pdf_pages")

    def test_image_pages_are_indexed_too(self, conn):
        document_id = _add_document(conn, "image", "/docs/a.png")
        Document.insert_image_page(
            conn, document_id, "h e l l o", 9, 0.9, None, None, None, None, 1, "0"
        )

        assert len(_match(conn, "image_pages", '"heiio"')) == 1
        conn.execute("DELETE FROM image_pages")
        assert _match(conn, "image_pages", '"heiio"') == []
        _check(conn, "image_pages")

    def test_the_noise_indexes_are_rebuildable_search_indexes(self):
        assert "pdf_pages_noise" in Document.SEARCH_INDEXES
        assert "image_pages_noise" in Document.SEARCH_INDEXES
        assert set(Document.TEXT_SEARCH_INDEXES) < set(Document.SEARCH_INDEXES)

    def test_rebuilding_refreshes_stale_skeletons_and_the_index(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "say h3ll0 now")])
        page_id = conn.execute("SELECT id FROM pdf_pages").fetchone()[0]
        # Something else wrote the page, leaving its skeleton behind (and the index with it).
        conn.execute("DROP TRIGGER pdf_pages_noise_au")
        conn.execute("UPDATE pdf_pages SET ocr_text = 'wholly new text'")
        conn.execute(Document.noise_triggers("pdf_pages")["pdf_pages_noise_au"])

        count = Document.rebuild_search_index(conn, "pdf_pages_noise")

        assert count == 1
        assert conn.execute("SELECT noise_text FROM pdf_pages").fetchone()[0] == Leet.skeleton(
            "wholly new text"
        )
        assert _match(conn, "pdf_pages", '"heiio"') == []
        assert _match(conn, "pdf_pages", _phrase("wholly")) == [page_id]
        _check(conn, "pdf_pages")
        # the UPDATE trigger it stepped aside is back
        triggers = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        assert "pdf_pages_noise_au" in triggers

    def test_refresh_only_touches_pages_that_are_out_of_date(self, conn):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(
            conn, [_pdf_row(document_id, 1, "up to date"), _pdf_row(document_id, 2, "stale")]
        )
        conn.execute("UPDATE pdf_pages SET noise_text = 'old' WHERE page_number = 2")

        assert Document.refresh_noise_text(conn, "pdf_pages") == 1
        assert Document.refresh_noise_text(conn, "pdf_pages") == 0
        with pytest.raises(ValueError):
            Document.refresh_noise_text(conn, "documents")

    def test_candidate_queries_narrow_through_the_index(self, conn, storage):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(
            conn,
            [
                _pdf_row(document_id, 1, "say h3ll0 now"),
                _pdf_row(document_id, 2, "something else entirely"),
            ],
        )

        everything = storage.search_noise_candidate_pdf_pages(None)
        narrowed = storage.search_noise_candidate_pdf_pages('"heiio"')

        assert [r["page_number"] for r in everything] == [1, 2]
        assert [r["page_number"] for r in narrowed] == [1]
        assert narrowed[0]["noise_text"] == Leet.skeleton("say h3ll0 now")
        assert narrowed[0]["ocr_text"] == "say h3ll0 now"

    def test_candidate_queries_always_include_pages_without_a_skeleton(self, conn, storage):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "say h3ll0 now")])
        conn.execute("UPDATE pdf_pages SET noise_text = ''")

        assert len(storage.search_noise_candidate_pdf_pages('"zzzzz"')) == 1

    def test_candidate_queries_skip_documents_that_are_not_indexed(self, conn, storage):
        document_id = _add_document(conn)
        Document.insert_pdf_pages(conn, [_pdf_row(document_id, 1, "say h3ll0 now")])
        conn.execute("UPDATE document_index SET status = 'error'")

        assert storage.search_noise_candidate_pdf_pages(None) == []
        assert storage.search_noise_candidate_image_pages(None) == []


class TestMigration:
    @staticmethod
    def _seed_v28(db_path):
        """A v28 database: pages without `noise_text`, and no noise indexes or triggers."""
        conn = Db.connect(db_path)
        conn.executescript(
            """
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/docs', 'folder', 'indexed', '2024-01-01');
            INSERT INTO documents (created_at) VALUES ('2024-01-01'), ('2024-01-01');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/a.pdf', 'pdf', 'indexed'),
                       (2, 1, 2, '/b.png', 'image', 'indexed');
            INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence)
                VALUES (1, 1, 'say h3ll0 now', 0.9), (1, 2, 'p@55w0rd', 0.9);
            INSERT INTO image_pages (document_id, ocr_text, confidence)
                VALUES (2, 'h . e l l o', 0.9);
            """
        )
        for table in ("pdf_pages", "image_pages"):
            for suffix in ("ai", "ad", "au"):
                conn.execute(f"DROP TRIGGER {table}_noise_{suffix}")
            conn.execute(f"DROP TABLE {table}_noise")
            conn.execute(f"ALTER TABLE {table} DROP COLUMN noise_text")
        conn.execute("UPDATE schema_version SET version = 28")
        conn.commit()
        conn.close()

    def test_adds_and_backfills_the_skeleton_and_builds_the_index(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v28(db_path)

        conn = Db.connect(db_path)
        try:
            skeletons = [r[0] for r in conn.execute("SELECT noise_text FROM pdf_pages ORDER BY id")]
            assert skeletons == [Leet.skeleton("say h3ll0 now"), "password"]
            assert conn.execute("SELECT noise_text FROM image_pages").fetchone()[0] == "heiio"
            assert len(_match(conn, "pdf_pages", '"password"')) == 1
            assert len(_match(conn, "pdf_pages", '"heiio"')) == 1
            assert len(_match(conn, "image_pages", '"heiio"')) == 1
            _check(conn, "pdf_pages")
            _check(conn, "image_pages")
            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_every_trigger_is_back_and_the_older_indexes_are_intact(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v28(db_path)

        conn = Db.connect(db_path)
        try:
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            }
            for table in ("pdf_pages", "image_pages"):
                for kind in ("trigram", "words", "noise"):
                    for suffix in ("ai", "ad", "au"):
                        assert f"{table}_{kind}_{suffix}" in names
            for index in ("pdf_pages_trigram", "pdf_pages_words", "image_pages_trigram"):
                conn.execute(f"INSERT INTO {index}({index}) VALUES ('integrity-check')")
            # and a page written now lands in all of them
            conn.execute(
                "INSERT INTO pdf_pages "
                "(document_id, page_number, ocr_text, noise_text, confidence) "
                "VALUES (1, 3, 'fresh', ?, 0.9)",
                (Leet.skeleton("fresh"),),
            )
            assert len(_match(conn, "pdf_pages", _phrase("fresh"))) == 1
            _check(conn, "pdf_pages")
        finally:
            conn.close()

    def test_a_fresh_database_has_it_all_at_the_current_version(self, tmp_path):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            assert {"pdf_pages_noise", "image_pages_noise"} <= tables
            assert Db.SCHEMA_VERSION == 29
        finally:
            conn.close()

    def test_migrating_from_before_the_word_indexes_works_too(self, tmp_path):
        # A v27 database: no noise_text, and indexes that the v28 step must build first.
        db_path = tmp_path / "vethuq.db"
        self._seed_v28(db_path)
        old = sqlite3.connect(db_path)
        old.execute("UPDATE schema_version SET version = 27")
        old.commit()
        old.close()

        conn = Db.connect(db_path)
        try:
            assert len(_match(conn, "pdf_pages", '"password"')) == 1
            conn.execute(
                "INSERT INTO pdf_pages_trigram(pdf_pages_trigram) VALUES ('integrity-check')"
            )
            _check(conn, "pdf_pages")
        finally:
            conn.close()
