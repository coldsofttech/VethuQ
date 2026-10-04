import sqlite3

import pytest
from vethuq_core.db import Db
from vethuq_core.db.queries.documents import Document

TELUGU = "కాకి అమ్మ ఇల్లు"
ENGLISH = "invoice total museum"
COMPLEX = ("pdf_pages_words_complex", "image_pages_words_complex")


def _seed(conn):
    conn.executescript(
        """
        INSERT INTO sources (id, path, source_type, status, added_at)
            VALUES (1, '/docs', 'folder', 'indexed', '2024-01-01');
        INSERT INTO documents (created_at) VALUES ('2024-01-01'), ('2024-01-01');
        INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
            VALUES (1, 1, 1, '/a.pdf', 'pdf', 'indexed'),
                   (2, 1, 2, '/b.png', 'image', 'indexed');
        """
    )


def _add_pdf_page(conn, text, page=1):
    return conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
        "VALUES (1, ?, ?, 0.9)",
        (page, text),
    ).lastrowid


def _match(conn, index, expression):
    sql = f"SELECT rowid FROM {index} WHERE {index} MATCH ?"
    return [r[0] for r in conn.execute(sql, (expression,))]


def _terms(conn, index):
    """The words an index currently holds (those with at least one page)."""
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS temp.v_{index} USING fts5vocab(main, {index}, row)"
    )
    return {r[0] for r in conn.execute(f"SELECT term FROM temp.v_{index} WHERE doc > 0")}


@pytest.fixture
def conn(tmp_path):
    connection = Db.connect(tmp_path / "vethuq.db")
    _seed(connection)
    yield connection
    connection.close()


class TestFreshDatabase:
    def test_has_the_language_columns_and_table(self, conn):
        assert "languages" in {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
        for table in ("pdf_pages", "image_pages"):
            columns = {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})")}
            assert columns["ocr_langs"]["dflt_value"] == "''"
        master = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "document_languages" in master

    def test_is_at_the_current_version(self, conn):
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 32
        assert Db.SCHEMA_VERSION == 32

    def test_has_the_mark_aware_word_indexes_and_triggers(self, conn):
        master = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}

        for index in COMPLEX:
            assert index in master
            for suffix in ("ai", "ad", "au"):
                assert f"{index}_{suffix}" in master

    def test_new_columns_default_for_existing_style_inserts(self, conn):
        page = _add_pdf_page(conn, "hello")

        assert (
            conn.execute("SELECT ocr_langs FROM pdf_pages WHERE id = ?", (page,)).fetchone()[0]
            == ""
        )
        assert conn.execute("SELECT languages FROM sources").fetchone()[0] is None


class TestDocumentLanguages:
    def test_rows_default_to_a_pending_default_pass(self, conn):
        conn.execute("INSERT INTO document_languages (document_id, language) VALUES (1, 'en')")
        row = conn.execute("SELECT * FROM document_languages").fetchone()

        assert (row["status"], row["source"], row["position"]) == ("pending", "default", 0)
        assert row["confidence"] is None

    def test_a_language_is_recorded_once_per_file(self, conn):
        conn.execute("INSERT INTO document_languages (document_id, language) VALUES (1, 'en')")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO document_languages (document_id, language) VALUES (1, 'en')")

    @pytest.mark.parametrize("column, value", [("status", "bogus"), ("source", "guessed")])
    def test_rejects_unknown_status_and_source(self, conn, column, value):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"INSERT INTO document_languages (document_id, language, {column}) "
                "VALUES (1, 'te', ?)",
                (value,),
            )

    def test_requires_an_existing_file(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO document_languages (document_id, language) VALUES (99, 'en')")

    def test_goes_with_its_file(self, conn):
        conn.execute("INSERT INTO document_languages (document_id, language) VALUES (2, 'te')")
        conn.execute("DELETE FROM document_index WHERE id = 2")

        assert conn.execute("SELECT COUNT(*) FROM document_languages").fetchone()[0] == 0


class TestComplexWordIndex:
    def test_telugu_words_are_kept_whole(self, conn):
        _add_pdf_page(conn, TELUGU)

        assert _terms(conn, "pdf_pages_words_complex") == {"కాకి", "అమ్మ", "ఇల్లు"}

    def test_the_plain_word_index_still_splits_them(self, conn):
        _add_pdf_page(conn, TELUGU)

        assert "కాకి" not in _terms(conn, "pdf_pages_words")

    def test_a_telugu_word_is_found_whole_not_as_its_consonants(self, conn):
        page = _add_pdf_page(conn, TELUGU)
        _add_pdf_page(conn, "క క", page=2)

        assert _match(conn, "pdf_pages_words_complex", '"కాకి"') == [page]
        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == [page]

    def test_prefix_matches(self, conn):
        page = _add_pdf_page(conn, "ఇల్లు ఇంట్లో")

        assert _match(conn, "pdf_pages_words_complex", '"ఇ" *') == [page]

    def test_english_pages_never_enter_it(self, conn):
        _add_pdf_page(conn, ENGLISH)
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (2, ?, 0.9)",
            (ENGLISH,),
        )

        for index in COMPLEX:
            assert _terms(conn, index) == set()

    def test_english_words_on_a_telugu_page_are_indexed_too(self, conn):
        page = _add_pdf_page(conn, f"invoice {TELUGU}")

        assert _match(conn, "pdf_pages_words_complex", '"invoice"') == [page]

    def test_the_plain_word_index_is_unchanged_by_telugu_pages(self, conn):
        english = _add_pdf_page(conn, ENGLISH)
        _add_pdf_page(conn, TELUGU, page=2)

        assert _match(conn, "pdf_pages_words", '"museum"') == [english]

    def test_image_pages_are_indexed(self, conn):
        row = conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (2, ?, 0.9)",
            (TELUGU,),
        ).lastrowid

        assert _match(conn, "image_pages_words_complex", '"అమ్మ"') == [row]

    def test_updating_the_text_moves_the_page_in_and_out(self, conn):
        page = _add_pdf_page(conn, ENGLISH)

        conn.execute("UPDATE pdf_pages SET ocr_text = ? WHERE id = ?", (TELUGU, page))
        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == [page]

        conn.execute("UPDATE pdf_pages SET ocr_text = ? WHERE id = ?", ("ఇల్లు", page))
        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == []
        assert _match(conn, "pdf_pages_words_complex", '"ఇల్లు"') == [page]

        conn.execute("UPDATE pdf_pages SET ocr_text = ? WHERE id = ?", (ENGLISH, page))
        assert _terms(conn, "pdf_pages_words_complex") == set()

    def test_updating_other_columns_leaves_it_alone(self, conn):
        page = _add_pdf_page(conn, TELUGU)

        conn.execute(
            "UPDATE pdf_pages SET confidence = 0.5, ocr_langs = 'te' WHERE id = ?", (page,)
        )

        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == [page]

    def test_deleting_a_page_removes_it(self, conn):
        page = _add_pdf_page(conn, TELUGU)
        conn.execute("DELETE FROM pdf_pages WHERE id = ?", (page,))

        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == []
        assert _terms(conn, "pdf_pages_words_complex") == set()


class TestRebuild:
    def test_refills_only_the_pages_that_belong(self, conn):
        telugu = _add_pdf_page(conn, TELUGU)
        _add_pdf_page(conn, ENGLISH, page=2)
        conn.execute(
            "INSERT INTO pdf_pages_words_complex(pdf_pages_words_complex) VALUES ('delete-all')"
        )
        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == []

        count = Document.rebuild_search_index(conn, "pdf_pages_words_complex")

        assert count == 1
        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == [telugu]
        assert _match(conn, "pdf_pages_words_complex", '"museum"') == []

    def test_is_repeatable(self, conn):
        telugu = _add_pdf_page(conn, TELUGU)

        Document.rebuild_search_index(conn, "pdf_pages_words_complex")
        Document.rebuild_search_index(conn, "pdf_pages_words_complex")

        assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == [telugu]

    def test_complex_indexes_are_among_the_rebuilt_ones(self):
        assert set(COMPLEX) <= set(Document.SEARCH_INDEXES)
        assert set(COMPLEX).isdisjoint(Document.TEXT_SEARCH_INDEXES)


class TestMigrationFromV31:
    @staticmethod
    def _seed_v31(db_path):
        """A v31 database: no language columns or table, no mark-aware indexes; one Telugu page
        and one English page already stored."""
        conn = Db.connect(db_path)
        _seed(conn)
        _add_pdf_page(conn, TELUGU)
        _add_pdf_page(conn, ENGLISH, page=2)
        for table in Document.PAGE_TABLES:
            for suffix in ("ai", "ad", "au"):
                conn.execute(f"DROP TRIGGER {table}_words_complex_{suffix}")
            conn.execute(f"DROP TABLE {table}_words_complex")
            conn.execute(f"ALTER TABLE {table} DROP COLUMN ocr_langs")
        conn.execute("DROP TABLE document_languages")
        conn.execute("ALTER TABLE sources DROP COLUMN languages")
        conn.execute("UPDATE schema_version SET version = 31")
        conn.commit()
        conn.close()

    def test_adds_the_columns_and_table(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v31(db_path)

        conn = Db.connect(db_path)
        try:
            assert "languages" in {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
            for table in ("pdf_pages", "image_pages"):
                assert "ocr_langs" in {
                    r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
                }
            assert conn.execute("SELECT COUNT(*) FROM document_languages").fetchone()[0] == 0
            assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 32
        finally:
            conn.close()

    def test_existing_pages_keep_reading_as_their_own_language(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v31(db_path)

        conn = Db.connect(db_path)
        try:
            assert {r[0] for r in conn.execute("SELECT ocr_langs FROM pdf_pages")} == {""}
        finally:
            conn.close()

    def test_only_the_telugu_page_is_indexed_for_complex_words(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v31(db_path)

        conn = Db.connect(db_path)
        try:
            telugu = conn.execute(
                "SELECT id FROM pdf_pages WHERE ocr_text = ?", (TELUGU,)
            ).fetchone()[0]
            assert _match(conn, "pdf_pages_words_complex", '"అమ్మ"') == [telugu]
            assert _terms(conn, "pdf_pages_words_complex") == {"కాకి", "అమ్మ", "ఇల్లు"}
        finally:
            conn.close()

    def test_the_plain_indexes_are_untouched(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v31(db_path)

        conn = Db.connect(db_path)
        try:
            english = conn.execute(
                "SELECT id FROM pdf_pages WHERE ocr_text = ?", (ENGLISH,)
            ).fetchone()[0]
            assert _match(conn, "pdf_pages_words", '"museum"') == [english]
        finally:
            conn.close()

    def test_reopening_is_a_no_op(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        self._seed_v31(db_path)
        Db.connect(db_path).close()

        conn = Db.connect(db_path)
        try:
            assert _terms(conn, "pdf_pages_words_complex") == {"కాకి", "అమ్మ", "ఇల్లు"}
        finally:
            conn.close()


class TestSqliteWithoutTheTokenizer:
    @pytest.fixture
    def unsupported(self, monkeypatch):
        monkeypatch.setattr(Document, "_complex_supported", False)

    def test_the_indexes_are_not_created_and_nothing_breaks(self, tmp_path, unsupported):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            master = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            assert master.isdisjoint(COMPLEX)

            _seed(conn)
            page = _add_pdf_page(conn, TELUGU)
            conn.execute("UPDATE pdf_pages SET ocr_text = ? WHERE id = ?", (ENGLISH, page))
            conn.execute("DELETE FROM pdf_pages WHERE id = ?", (page,))
        finally:
            conn.close()

    def test_rebuilding_them_has_nothing_to_do(self, tmp_path, unsupported):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            assert Document.rebuild_search_index(conn, "pdf_pages_words_complex") == 0
        finally:
            conn.close()

    def test_support_is_probed_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Document, "_complex_supported", None)
        conn = sqlite3.connect(":memory:")
        try:
            assert Document.complex_words_supported(conn) is True
            assert Document._complex_supported is True
        finally:
            conn.close()
