import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.ocr import Quick
from vethuq_core.source import Sources


def _fake_ocr_result(text: str = "hello world", score: float = 0.95):
    return [{"rec_texts": [text], "rec_scores": [score]}]


class TestQuick:
    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_indexes_image_file(self, mock_get_engine, conn: sqlite3.Connection, tmp_path):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, image_path)

        Quick.run(conn, source)

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()
        assert doc["status"] == "indexed"
        assert doc["file_type"] == "image"

        page = conn.execute(
            "SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["ocr_text"] == "hello world"
        assert page["confidence"] == pytest.approx(0.95)

        updated_source = conn.execute(
            "SELECT status FROM sources WHERE id = ?", (source.id,)
        ).fetchone()
        assert updated_source["status"] == "indexed"
        assert doc["file_size_bytes"] == image_path.stat().st_size
        assert doc["created_at"] is not None
        assert doc["modified_at"] is not None

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_marks_document_processing_while_in_flight(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        captured: dict[str, object] = {}

        def _predict(_image):
            row = conn.execute(
                "SELECT status, started_at FROM document_index WHERE file_path = ?",
                (str(image_path.resolve()),),
            ).fetchone()
            captured["status"] = row["status"]
            captured["started_at"] = row["started_at"]
            return _fake_ocr_result()

        engine = MagicMock()
        engine.predict.side_effect = _predict
        mock_get_engine.return_value = engine

        source = Sources.add(conn, image_path)

        Quick.run(conn, source)

        assert captured["status"] == "processing"
        assert captured["started_at"] is not None

        doc = conn.execute(
            "SELECT status FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()
        assert doc["status"] == "indexed"

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_skips_file_already_claimed_by_another_run(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, image_path)

        # Simulate another concurrently-running index run having already claimed
        # this file - its document_index row is mid-processing.
        now = "2026-01-01T00:00:00+00:00"
        other_run_document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (now,)
        ).lastrowid
        conn.execute(
            "INSERT INTO document_index "
            "(source_id, document_id, file_path, file_type, status, started_at) "
            "VALUES (?, ?, ?, 'image', 'processing', ?)",
            (source.id, other_run_document_id, str(image_path.resolve()), now),
        )
        conn.commit()

        processed = Quick.run(conn, source)

        assert processed == []
        engine.predict.assert_not_called()
        doc = conn.execute(
            "SELECT status, document_id FROM document_index WHERE file_path = ?",
            (str(image_path.resolve()),),
        ).fetchone()
        assert doc["status"] == "processing"
        assert doc["document_id"] == other_run_document_id

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_links_duplicate_content_without_rerunning_ocr(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"identical bytes")
        (folder / "b.png").write_bytes(b"identical bytes")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)

        assert engine.predict.call_count == 1

        docs = conn.execute("SELECT * FROM document_index").fetchall()
        assert len(docs) == 2
        carriers = [
            doc
            for doc in docs
            if conn.execute(
                "SELECT 1 FROM image_pages WHERE document_id = ?", (doc["id"],)
            ).fetchone()
            is not None
        ]
        duplicates = [doc for doc in docs if doc not in carriers]
        assert len(carriers) == 1
        assert len(duplicates) == 1
        original, duplicate = carriers[0], duplicates[0]

        assert original["status"] == "indexed"
        assert duplicate["status"] == "indexed"
        assert duplicate["document_id"] == original["document_id"]
        assert original["sha256"] == duplicate["sha256"]

        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM image_pages WHERE document_id = ?", (duplicate["id"],)
            ).fetchone()["n"]
            == 0
        )

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_promotes_duplicate_when_original_is_modified(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("shared content")
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        file1 = folder / "a.png"
        file2 = folder / "b.png"
        file1.write_bytes(b"identical bytes")
        file2.write_bytes(b"identical bytes")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)

        doc1 = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(file1.resolve()),)
        ).fetchone()
        doc2 = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(file2.resolve()),)
        ).fetchone()
        # file1 ("a.png") is processed first, so it carries the OCR pages; file2
        # ("b.png") just links to the same logical document.
        assert (
            conn.execute(
                "SELECT 1 FROM image_pages WHERE document_id = ?", (doc1["id"],)
            ).fetchone()
            is not None
        )
        assert doc2["document_id"] == doc1["document_id"]

        # file1 (the original) gets modified; file2 (the duplicate) is untouched.
        new_mtime = file1.stat().st_mtime + 5
        file1.write_bytes(b"totally different, longer content now")
        os.utime(file1, (new_mtime, new_mtime))
        engine.predict.return_value = _fake_ocr_result("new content for file1")

        second_run = Quick.run(conn, source, only_new_files=True)

        # Only file1 needed reprocessing - file2's own bytes never changed.
        assert second_run == [str(file1.resolve())]

        doc1_after = conn.execute(
            "SELECT * FROM document_index WHERE id = ?", (doc1["id"],)
        ).fetchone()
        doc2_after = conn.execute(
            "SELECT * FROM document_index WHERE id = ?", (doc2["id"],)
        ).fetchone()

        # file2 is promoted back to being its own logical document (keeping the
        # old shared document_id) rather than silently inheriting file1's new,
        # unrelated content; file1 moves on to a brand-new logical document.
        assert doc2_after["document_id"] == doc1["document_id"]
        assert doc1_after["document_id"] != doc1["document_id"]
        assert doc1_after["document_id"] != doc2_after["document_id"]

        page1 = conn.execute(
            "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc1["id"],)
        ).fetchone()
        assert page1["ocr_text"] == "new content for file1"

        page2 = conn.execute(
            "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc2["id"],)
        ).fetchone()
        assert page2["ocr_text"] == "shared content"

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_updates_processing_metrics_on_success(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result(score=0.8)
        mock_get_engine.return_value = engine

        first = tmp_path / "first.png"
        first.write_bytes(b"fake png bytes")
        Quick.run(conn, Sources.add(conn, first))

        metrics = conn.execute(
            "SELECT * FROM processing_metrics WHERE file_type = 'image'"
        ).fetchone()
        assert metrics["document_count"] == 1

        confidence = conn.execute(
            "SELECT * FROM confidence_metrics WHERE file_type = 'image' AND process_type = 'ocr'"
        ).fetchone()
        assert confidence["page_count"] == 1
        assert confidence["avg_confidence"] == pytest.approx(0.8)

        engine.predict.return_value = _fake_ocr_result(score=0.6)
        second = tmp_path / "second.png"
        second.write_bytes(b"more fake png bytes")
        Quick.run(conn, Sources.add(conn, second))

        metrics = conn.execute(
            "SELECT * FROM processing_metrics WHERE file_type = 'image'"
        ).fetchone()
        assert metrics["document_count"] == 2

        confidence = conn.execute(
            "SELECT * FROM confidence_metrics WHERE file_type = 'image' AND process_type = 'ocr'"
        ).fetchone()
        assert confidence["page_count"] == 2
        assert confidence["avg_confidence"] == pytest.approx(0.7)

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_does_not_update_processing_metrics_on_error(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.side_effect = RuntimeError("ocr blew up")
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        Quick.run(conn, Sources.add(conn, image_path))

        assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
        assert conn.execute("SELECT * FROM confidence_metrics").fetchone() is None

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_skips_unsupported_files(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "notes.txt").write_text("not ocr-able")
        (folder / "scan.jpg").write_bytes(b"fake jpg bytes")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)

        docs = conn.execute("SELECT file_path FROM document_index").fetchall()
        assert len(docs) == 1
        assert docs[0]["file_path"].endswith("scan.jpg")

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_records_error_without_aborting(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.side_effect = RuntimeError("ocr blew up")
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, image_path)

        Quick.run(conn, source)

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()
        assert doc["status"] == "error"
        assert "ocr blew up" in doc["error_message"]

        updated_source = conn.execute(
            "SELECT status FROM sources WHERE id = ?", (source.id,)
        ).fetchone()
        assert updated_source["status"] == "error"

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_rerun_replaces_stale_page_rows(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("first pass")
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, image_path)
        Quick.run(conn, source)

        engine.predict.return_value = _fake_ocr_result("second pass")
        Quick.run(conn, source)

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()
        pages = conn.execute(
            "SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)
        ).fetchall()
        assert len(pages) == 1
        assert pages[0]["ocr_text"] == "second pass"

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_only_new_files_skips_already_indexed(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("first file")
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "first.png").write_bytes(b"fake png bytes")
        source = Sources.add(conn, folder)

        first_run = Quick.run(conn, source)
        assert first_run == [str((folder / "first.png").resolve())]

        # A new file shows up in the folder after the source is already indexed.
        (folder / "second.png").write_bytes(b"fake png bytes")
        engine.predict.return_value = _fake_ocr_result("second file")

        second_run = Quick.run(conn, source, only_new_files=True)

        assert second_run == [str((folder / "second.png").resolve())]

        docs = {
            row["file_path"]: row["status"]
            for row in conn.execute("SELECT file_path, status FROM document_index")
        }
        assert docs[str((folder / "first.png").resolve())] == "indexed"
        assert docs[str((folder / "second.png").resolve())] == "indexed"

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_only_new_files_reindexes_modified_file(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("original content")
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"original bytes")
        source = Sources.add(conn, image_path)

        Quick.run(conn, source)
        doc = conn.execute(
            "SELECT id FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()

        # Edit the file's content and bump its mtime so the fast path notices.
        new_mtime = image_path.stat().st_mtime + 5
        image_path.write_bytes(b"changed bytes, a different length than before")
        os.utime(image_path, (new_mtime, new_mtime))
        engine.predict.return_value = _fake_ocr_result("updated content")

        second_run = Quick.run(conn, source, only_new_files=True)

        assert second_run == [str(image_path.resolve())]
        page = conn.execute(
            "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["ocr_text"] == "updated content"

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_only_new_files_skips_unchanged_file_without_rehashing(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("original content")
        mock_get_engine.return_value = engine

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"original bytes")
        source = Sources.add(conn, image_path)

        Quick.run(conn, source)

        with patch("vethuq_core.ocr.Document.compute_sha256") as mock_checksum:
            second_run = Quick.run(conn, source, only_new_files=True)
            mock_checksum.assert_not_called()

        assert second_run == []

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_only_new_files_detects_plain_rename(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("original text")
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        old_path = folder / "scan.png"
        old_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)
        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(old_path.resolve()),)
        ).fetchone()

        new_path = folder / "renamed.png"
        old_path.rename(new_path)

        second_run = Quick.run(conn, source, only_new_files=True)

        assert engine.predict.call_count == 1  # no re-OCR for a plain rename
        assert second_run == [str(new_path.resolve())]

        updated = conn.execute("SELECT * FROM document_index WHERE id = ?", (doc["id"],)).fetchone()
        assert updated["file_path"] == str(new_path.resolve())
        assert updated["status"] == "indexed"
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM document_index WHERE file_path = ?",
                (str(old_path.resolve()),),
            ).fetchone()["n"]
            == 0
        )

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_only_new_files_marks_missing_file_removed(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        image_path = folder / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)
        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()
        assert doc["status"] == "indexed"

        image_path.unlink()
        second_run = Quick.run(conn, source, only_new_files=True)

        assert second_run == []
        updated = conn.execute(
            "SELECT status, removed_at FROM document_index WHERE id = ?", (doc["id"],)
        ).fetchone()
        assert updated["status"] == "removed"
        assert updated["removed_at"] is not None

    @patch("vethuq_core.ocr.Engine.get")
    def test_run_ocr_handles_duplicate_original_deleted_and_duplicate_renamed(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = MagicMock()
        engine.predict.return_value = _fake_ocr_result("shared content")
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        file_a = folder / "a.png"
        file_b = folder / "b.png"
        file_a.write_bytes(b"identical bytes")
        file_b.write_bytes(b"identical bytes")
        source = Sources.add(conn, folder)

        Quick.run(conn, source)

        doc_a = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(file_a.resolve()),)
        ).fetchone()
        doc_b = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(file_b.resolve()),)
        ).fetchone()
        assert (
            conn.execute(
                "SELECT 1 FROM image_pages WHERE document_id = ?", (doc_a["id"],)
            ).fetchone()
            is not None
        )
        assert doc_b["document_id"] == doc_a["document_id"]

        # The original (file_a) is deleted outright; the duplicate (file_b) is
        # renamed rather than touched.
        file_c = folder / "c.png"
        file_a.unlink()
        file_b.rename(file_c)

        second_run = Quick.run(conn, source, only_new_files=True)

        # No OCR needed - the content at file_c already matches an indexed row.
        assert engine.predict.call_count == 1
        assert second_run == [str(file_c.resolve())]

        rows_by_id = {
            row["id"]: row
            for row in conn.execute(
                "SELECT * FROM document_index WHERE id IN (?, ?)", (doc_a["id"], doc_b["id"])
            )
        }
        survivor = rows_by_id[doc_a["id"]]
        gone = rows_by_id[doc_b["id"]]

        assert survivor["file_path"] == str(file_c.resolve())
        assert survivor["status"] == "indexed"
        assert gone["status"] == "removed"
        assert gone["removed_at"] is not None
        assert gone["document_id"] == survivor["document_id"]

        page = conn.execute(
            "SELECT ocr_text FROM image_pages WHERE document_id = ?", (survivor["id"],)
        ).fetchone()
        assert page["ocr_text"] == "shared content"
