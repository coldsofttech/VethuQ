import sqlite3

import pytest
from vethuq_core.db import Db
from vethuq_core.db.queries.documents import Document
from vethuq_core.index import AlreadyRunningError, IndexRunner, SearchIndexRebuild


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


def test_rebuilds_every_search_index_and_reports_progress(db_path):
    seen = []
    result = SearchIndexRebuild.run(db_path=db_path, on_progress=lambda *a: seen.append(a))

    assert result.ok
    assert list(result.rebuilt) == list(Document.SEARCH_INDEXES)
    assert [s[0] for s in seen] == list(Document.SEARCH_INDEXES)
    total = len(Document.SEARCH_INDEXES)
    assert [s[1:] for s in seen] == [(i, total) for i in range(1, total + 1)]


def test_one_failing_index_does_not_stop_the_others(db_path, monkeypatch):
    real = Document.rebuild_search_index

    def flaky(conn, index):
        if index == "pdf_pages_words":
            raise sqlite3.DatabaseError("malformed")
        return real(conn, index)

    monkeypatch.setattr(Document, "rebuild_search_index", staticmethod(flaky))
    result = SearchIndexRebuild.run(db_path=db_path)

    assert not result.ok
    assert result.failed == {"pdf_pages_words": "malformed"}
    assert len(result.rebuilt) == len(Document.SEARCH_INDEXES) - 1


def test_refuses_while_an_index_run_is_active(db_path, monkeypatch):
    monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda _p: (True, 99)))
    with pytest.raises(AlreadyRunningError):
        SearchIndexRebuild.run(db_path=db_path)


def test_rebuild_restores_search_over_stored_page_text(db_path):
    conn = Db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources (path, source_type, added_at) "
            "VALUES ('/x', 'folder', '2026-01-01')"
        )
        logical_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
        ).lastrowid
        doc_id = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type) "
            "VALUES (1, ?, '/x/a.pdf', 'pdf')",
            (logical_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source) "
            "VALUES (?, 1, 'quarterly invoice total', 1.0, 'native')",
            (doc_id,),
        )
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence) "
            "VALUES (?, 'scanned receipt', 0.9)",
            (doc_id,),
        )
        for index in Document.SEARCH_INDEXES:
            conn.execute(f"INSERT INTO {index}({index}) VALUES ('delete-all')")
        conn.commit()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pdf_pages_trigram WHERE pdf_pages_trigram MATCH 'invoice'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()

    result = SearchIndexRebuild.run(db_path=db_path)

    assert result.ok
    assert result.rebuilt["pdf_pages_trigram"] == 1
    assert result.rebuilt["image_pages_words"] == 1
    conn = Db.connect(db_path)
    try:
        for index, term in (
            ("pdf_pages_trigram", "invoice"),
            ("pdf_pages_words", "quarterly"),
            ("image_pages_trigram", "receipt"),
            ("image_pages_words", "scanned"),
        ):
            hits = conn.execute(f"SELECT COUNT(*) FROM {index} WHERE {index} MATCH ?", (term,))
            assert hits.fetchone()[0] == 1, index
    finally:
        conn.close()


def test_unknown_search_index_is_rejected(db_path):
    conn = Db.connect(db_path)
    try:
        with pytest.raises(ValueError):
            Document.rebuild_search_index(conn, "documents")
    finally:
        conn.close()
