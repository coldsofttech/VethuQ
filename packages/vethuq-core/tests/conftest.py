from unittest.mock import MagicMock

import pytest
from vethuq_core.db import Db
from vethuq_core.ocr.engines.paddle import PaddleOcrEngine
from vethuq_core.paths import Paths
from vethuq_core.storage.sqlite import SqliteStorage


@pytest.fixture
def conn(tmp_path):
    # check_same_thread=False: batch OCR hands this connection to worker threads,
    # same as the real index worker does.
    connection = Db.connect(tmp_path / "vethuq.db", check_same_thread=False)
    yield connection
    connection.close()


@pytest.fixture
def storage(conn):
    """A `Storage` sharing the test's raw `conn`, so tests can assert on rows directly."""
    return SqliteStorage(conn)


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path_factory, monkeypatch):
    """Keep tests from creating db/, run/ or logs/ folders in the real per-user data dir."""
    root = tmp_path_factory.mktemp("data_root")
    monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: root))


class PaddleStub(PaddleOcrEngine):
    """A `PaddleOcrEngine` whose PaddleOCR is itself: set `predict` to fake what Paddle returns."""

    def __init__(self) -> None:
        self.predict = MagicMock()
        self._ocr = self
        self._name = "paddleocr test"
