"""Processing/confidence statistics are tracked per file extension, not per file type."""

import sqlite3
from unittest.mock import patch

import pytest
from conftest import PaddleStub
from vethuq_core.ocr import Quick
from vethuq_core.paths.extensions import Extensions
from vethuq_core.readers.storage import PageResult
from vethuq_core.sources import Sources
from vethuq_core.stats import Confidence, Processing
from vethuq_core.storage import Storage


class TestExtensions:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/docs/Report.PDF", "pdf"),
            ("scan.png", "png"),
            ("photo.jpg", "jpg"),
            ("photo.JPEG", "jpg"),
            ("C:\\scans\\a.Png", "png"),
            ("archive.tar.gz", "gz"),
            ("/docs/noextension", ""),
        ],
    )
    def test_of_normalizes_the_extension(self, path, expected):
        assert Extensions.of(path) == expected


def _ocr(text="hello", score=0.9):
    return [{"rec_texts": [text], "rec_scores": [score]}]


class TestPerExtensionTracking:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_png_and_jpg_are_tracked_separately(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        mock_get_engine.return_value = engine
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"png bytes")
        (folder / "b.jpg").write_bytes(b"jpg bytes")
        source = Sources.add(storage, folder)

        engine.predict.return_value = _ocr(score=0.8)
        Quick.run(storage, source)

        processing = {(m.extension, m.file_type): m for m in Processing.get_metrics(storage)}
        assert set(processing) == {("png", "image"), ("jpg", "image")}
        assert all(m.document_count == 1 for m in processing.values())
        confidence = {(m.extension, m.process_type): m for m in Confidence.get_metrics(storage)}
        assert set(confidence) == {("png", "ocr"), ("jpg", "ocr")}
        assert all(m.page_count == 1 for m in confidence.values())

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_each_extension_keeps_its_own_running_average(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        mock_get_engine.return_value = PaddleStub()
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"first png")
        (folder / "b.png").write_bytes(b"second png")
        (folder / "c.jpg").write_bytes(b"a jpg")
        source = Sources.add(storage, folder)
        scores = {"a.png": 0.6, "b.png": 1.0, "c.jpg": 0.2}

        def extract(storage_, reader, file_path, db_lock=None):
            return [PageResult("text", scores[file_path.name], "ocr")], 1, None

        # Hand pages straight in: this test is about the bookkeeping, not about OCR.
        with patch("vethuq_core.ocr.quick.Quick.run_with_retries", side_effect=extract):
            Quick.run(storage, source)

        confidence = {m.extension: m for m in Confidence.get_metrics(storage)}
        assert confidence["png"].page_count == 2
        assert confidence["png"].avg_confidence == pytest.approx(0.8)
        assert confidence["jpg"].page_count == 1
        assert confidence["jpg"].avg_confidence == pytest.approx(0.2)

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_jpeg_files_count_as_jpg(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _ocr()
        mock_get_engine.return_value = engine
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.jpg").write_bytes(b"one")
        (folder / "b.jpeg").write_bytes(b"two")
        source = Sources.add(storage, folder)

        Quick.run(storage, source)

        metrics = Processing.get_metrics(storage)
        assert [(m.extension, m.document_count) for m in metrics] == [("jpg", 2)]
