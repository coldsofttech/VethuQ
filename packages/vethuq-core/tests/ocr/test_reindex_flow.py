"""A full re-index end to end: content stays searchable, nothing is duplicated."""

import sqlite3
from unittest.mock import patch

from conftest import PaddleStub
from vethuq_core.ocr import Quick
from vethuq_core.search import Search
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage


def _ocr(text: str):
    return [{"rec_texts": [text], "rec_scores": [0.95]}]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _queue(storage: Storage, source_id: int) -> None:
    with storage.transaction():
        storage.reset_document_index_for_reindex(source_id)


def _hits(storage: Storage, query: str) -> list[str]:
    return [m.file_name for m in Search.indexed_content(storage, query)]


class TestReindexFlow:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_reindexes_every_file_without_creating_documents(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _ocr("first pass")
        mock_get_engine.return_value = engine
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"aaa")
        (folder / "b.png").write_bytes(b"bbb")
        source = Sources.add(storage, folder)
        Quick.run(storage, source)
        documents_before = _count(conn, "documents")
        calls_before = engine.predict.call_count

        engine.predict.return_value = _ocr("second pass")
        _queue(storage, source.id)
        Quick.run(storage, source, only_new_files=True)

        assert engine.predict.call_count == calls_before + 2
        assert _count(conn, "documents") == documents_before
        assert _count(conn, "image_pages") == 2
        assert (
            conn.execute("SELECT DISTINCT status FROM document_index").fetchall()[0][0] == "indexed"
        )
        assert conn.execute("SELECT SUM(reindex_pending) FROM document_index").fetchone()[0] == 0
        assert sorted(_hits(storage, "second pass")) == ["a.png", "b.png"]
        assert _hits(storage, "first pass") == []

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_queued_files_stay_searchable_until_reprocessed(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _ocr("original text")
        mock_get_engine.return_value = engine
        image = tmp_path / "scan.png"
        image.write_bytes(b"scan")
        source = Sources.add(storage, image)
        Quick.run(storage, source)

        _queue(storage, source.id)

        assert _hits(storage, "original text") == ["scan.png"]

        seen_while_processing: list[list[str]] = []

        def predict(*args, **kwargs):
            seen_while_processing.append(_hits(storage, "original text"))
            return _ocr("new text")

        engine.predict.side_effect = predict
        Quick.run(storage, source, only_new_files=True)

        assert seen_while_processing == [["scan.png"]]
        assert _hits(storage, "new text") == ["scan.png"]

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_failed_reprocess_keeps_previous_content(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _ocr("original text")
        mock_get_engine.return_value = engine
        image = tmp_path / "scan.png"
        image.write_bytes(b"scan")
        source = Sources.add(storage, image)
        Quick.run(storage, source)

        engine.predict.side_effect = RuntimeError("ocr blew up")
        _queue(storage, source.id)
        Quick.run(storage, source, only_new_files=True)

        row = conn.execute("SELECT status, reindex_pending FROM document_index").fetchone()
        assert (row["status"], row["reindex_pending"]) == ("error", 1)
        assert _hits(storage, "original text") == ["scan.png"]

        # A later successful run (or `index restart`) finishes the job and clears the queue.
        engine.predict.side_effect = None
        engine.predict.return_value = _ocr("recovered text")
        Quick.run(storage, source, only_new_files=True)

        assert conn.execute("SELECT status, reindex_pending FROM document_index").fetchone()[:] == (
            "indexed",
            0,
        )
        assert _hits(storage, "recovered text") == ["scan.png"]

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_identical_files_keep_a_single_original_after_reindex(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _ocr("shared text")
        mock_get_engine.return_value = engine
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "b.png").write_bytes(b"identical")
        source = Sources.add(storage, folder)
        Quick.run(storage, source)
        # a.png arrives later, so b.png is the original and a.png the duplicate...
        (folder / "a.png").write_bytes(b"identical")
        Quick.run(storage, source, only_new_files=True)
        assert _count(conn, "image_pages") == 1

        # ...but a re-index reprocesses a.png first, which makes it the original.
        _queue(storage, source.id)
        Quick.run(storage, source, only_new_files=True)

        assert _count(conn, "documents") == 1
        assert _count(conn, "image_pages") == 1
        assert len(Search.indexed_content(storage, "shared text")) == 2
