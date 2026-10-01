import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.db import Db
from vethuq_core.ocr import Quick
from vethuq_core.source import Sources

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "jpg"

_JPG_FIXTURES = sorted(FIXTURES_DIR.glob("*.jpg"), key=lambda path: int(path.name.split("_")[0]))


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = Db.connect(db_path)
    yield connection
    connection.close()


def test_jpg_fixtures_are_present():
    assert len(_JPG_FIXTURES) == 21


@pytest.mark.integration
@pytest.mark.parametrize("fixture_path", _JPG_FIXTURES, ids=[p.stem for p in _JPG_FIXTURES])
@patch("vethuq_core.ocr.Engine.get")
def test_run_ocr_fixture_jpg_indexes_as_single_image_page(
    mock_get_engine, fixture_path: Path, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = [{"rec_texts": ["ocr text"], "rec_scores": [0.9]}]
    mock_get_engine.return_value = engine

    jpg_path = tmp_path / "scan.jpg"
    jpg_path.write_bytes(fixture_path.read_bytes())
    source = Sources.add(conn, jpg_path)

    Quick.run(conn, source)

    engine.predict.assert_called_once()

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(jpg_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "indexed"
    assert doc["file_type"] == "image"
    assert doc["file_size_bytes"] == fixture_path.stat().st_size

    pages = conn.execute("SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)).fetchall()
    assert len(pages) == 1
    assert pages[0]["ocr_text"] == "ocr text"
    assert pages[0]["confidence"] == pytest.approx(0.9)
