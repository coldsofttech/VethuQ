import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.db import Db
from vethuq_core.ocr import Quick
from vethuq_core.source import Sources

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "png"

_PNG_FIXTURES = sorted(FIXTURES_DIR.glob("*.png"), key=lambda path: int(path.name.split("_")[0]))


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = Db.connect(db_path)
    yield connection
    connection.close()


def test_png_fixtures_are_present():
    assert len(_PNG_FIXTURES) == 18


@pytest.mark.integration
@pytest.mark.parametrize("fixture_path", _PNG_FIXTURES, ids=[p.stem for p in _PNG_FIXTURES])
@patch("vethuq_core.ocr.Engine.get")
def test_run_ocr_fixture_png_indexes_as_single_image_page(
    mock_get_engine, fixture_path: Path, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = [{"rec_texts": ["ocr text"], "rec_scores": [0.9]}]
    mock_get_engine.return_value = engine

    png_path = tmp_path / "scan.png"
    png_path.write_bytes(fixture_path.read_bytes())
    source = Sources.add(conn, png_path)

    Quick.run(conn, source)

    engine.predict.assert_called_once()

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(png_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "indexed"
    assert doc["file_type"] == "image"
    assert doc["file_size_bytes"] == fixture_path.stat().st_size

    pages = conn.execute("SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)).fetchall()
    assert len(pages) == 1
    assert pages[0]["ocr_text"] == "ocr text"
    assert pages[0]["confidence"] == pytest.approx(0.9)
