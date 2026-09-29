import logging
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.db import Db
from vethuq_core.logs import Logs
from vethuq_core.ocr import Quick
from vethuq_core.search import Search
from vethuq_core.sources import Sources


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _attach(component):
    logger = Logs.get_logger(component)
    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return handler


@pytest.fixture
def index_log():
    return _attach("index")


@pytest.fixture
def database_log():
    return _attach("database")


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    for component in ("index", "database"):
        logger = Logs.get_logger(component)
        for handler in [h for h in logger.handlers if isinstance(h, _Capture)]:
            logger.removeHandler(handler)


class TestFailureLogging:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_ocr_failure_logs_file_page_engine_and_exception(
        self, mock_get_engine, conn, storage, tmp_path, index_log
    ):
        engine = MagicMock()
        engine.name = "fake-ocr 1.0"
        engine.recognize.side_effect = RuntimeError("ocr blew up")
        mock_get_engine.return_value = engine
        image = tmp_path / "scan.png"
        image.write_bytes(b"fake png bytes")
        source = Sources.add(storage, image)

        with patch("vethuq_core.settings.OcrSettings.get_retry_attempts", return_value=0):
            Quick.run(storage, source)

        text = "\n".join(index_log.messages)
        assert "OCR failed" in text and "scan.png" in text and "page=1" in text
        assert "engine=fake-ocr 1.0" in text and "RuntimeError: ocr blew up" in text
        assert "Indexing failed" in text and "source_id=" in text

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_extraction_failure_is_logged(
        self, mock_get_engine, conn, storage, tmp_path, index_log
    ):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"this is not a pdf at all")
        source = Sources.add(storage, bad)

        Quick.run(storage, source)

        text = "\n".join(index_log.messages)
        assert "Extraction failed" in text and "bad.pdf" in text

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_scan_start_and_end_are_logged(
        self, mock_get_engine, conn, storage, tmp_path, index_log
    ):
        folder = tmp_path / "docs"
        folder.mkdir()
        source = Sources.add(storage, folder)

        Quick.run(storage, source)

        text = "\n".join(index_log.messages)
        assert "Scanning source" in text and "0 supported file(s) found" in text
        assert "finished: indexed" in text

    def test_search_failure_is_logged_and_reraised(self, conn, storage, database_log):
        with patch("vethuq_core.search.search.SearchEngines.get") as get_engine:
            get_engine.return_value.search.side_effect = sqlite3.OperationalError("disk I/O error")
            with pytest.raises(sqlite3.OperationalError):
                Search.indexed_content(storage, "invoice")

        text = "\n".join(database_log.messages)
        assert (
            "Search failed" in text
            and "query_length=7" in text
            and "invoice" not in text
            and "disk I/O error" in text
        )

    def test_database_open_failure_is_logged(self, tmp_path, database_log):
        # connect() re-points the logger at the data dir's file, dropping the capture handler.
        with patch("vethuq_core.logs.Logs.setup"), pytest.raises(sqlite3.Error):
            Db.connect(tmp_path)  # a directory can't be opened as a database

        assert any("Could not open database" in m for m in database_log.messages)
