import sqlite3
from pathlib import Path
from unittest.mock import patch

import pdf_factory
from conftest import PaddleStub
from vethuq_core.ocr import Quick
from vethuq_core.readers import ImagePageStorage, PageResult, PdfPageStorage
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage


def _index_pdf(conn: sqlite3.Connection, storage: Storage, tmp_path: Path) -> int:
    """Index a small native PDF made for the test."""
    Quick.run(storage, Sources.add(storage, pdf_factory.native(tmp_path / "doc.pdf")))
    return conn.execute("SELECT id FROM document_index").fetchone()["id"]


class TestImagePageStorage:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_reads_back_confidences(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = [{"rec_texts": ["hello"], "rec_scores": [0.9]}]
        mock_get_engine.return_value = engine
        path = tmp_path / "doc.png"
        path.write_bytes(b"x")
        Quick.run(storage, Sources.add(storage, path))
        document_id = conn.execute("SELECT id FROM document_index").fetchone()["id"]

        page_storage = ImagePageStorage()

        assert page_storage.page_confidences(storage, document_id) == [0.9]
        assert page_storage.confidences_by_process_type(storage, document_id) == {"ocr": [0.9]}
        assert page_storage.confidences_by_process_type(storage, document_id + 1) == {}


class TestPdfPageStorage:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_groups_by_source_and_replaces_on_restore(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        # A digital PDF is read from its text layer, so no engine is involved.
        document_id = _index_pdf(conn, storage, tmp_path)
        page_storage = PdfPageStorage()

        grouped = page_storage.confidences_by_process_type(storage, document_id)
        assert set(grouped) == {"native"}
        assert set(grouped["native"]) == {1.0}

        page_storage.store(
            storage,
            document_id,
            [
                PageResult(text="b", confidence=0.5, source="ocr"),
                PageResult(text="c", confidence=0.7, source="ocr"),
                PageResult(text="d", confidence=0.6, source="mixed"),
            ],
        )

        assert page_storage.page_confidences(storage, document_id) == [0.5, 0.7, 0.6]
        assert page_storage.confidences_by_process_type(storage, document_id) == {
            "ocr": [0.5, 0.7],
            "mixed": [0.6],
        }
