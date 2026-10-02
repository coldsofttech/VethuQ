import sqlite3
from unittest.mock import patch

from conftest import PaddleStub
from vethuq_core.ocr import Quick
from vethuq_core.source import Sources


def _fake_ocr_result(text: str = "hello world", score: float = 0.95):
    return [{"rec_texts": [text], "rec_scores": [score]}]


class TestPurgeDocuments:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_purge_promotes_duplicate_when_original_document_is_removed(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        engine = PaddleStub()
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
        assert doc_b["document_id"] == doc_a["document_id"]

        # file_a (the original) is deleted outright, with nothing to rename it to.
        file_a.unlink()
        Quick.run(conn, source, only_new_files=True)

        removed = conn.execute(
            "SELECT status, removed_at FROM document_index WHERE id = ?", (doc_a["id"],)
        ).fetchone()
        assert removed["status"] == "removed"
        assert removed["removed_at"] is not None

        Sources.purge_expired_documents(conn, retention_minutes=-1)

        survivor = conn.execute(
            "SELECT * FROM document_index WHERE id = ?", (doc_b["id"],)
        ).fetchone()
        assert survivor["document_id"] == doc_a["document_id"]
        assert survivor["status"] == "indexed"
        assert (
            conn.execute("SELECT * FROM documents WHERE id = ?", (doc_a["document_id"],)).fetchone()
            is not None
        )

        page = conn.execute(
            "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc_b["id"],)
        ).fetchone()
        assert page["ocr_text"] == "shared content"

        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM document_index WHERE id = ?", (doc_a["id"],)
            ).fetchone()["n"]
            == 0
        )
