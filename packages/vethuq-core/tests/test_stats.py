import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.db import connect
from vethuq_core.stats import get_confidence_metrics, get_processing_metrics, reset_metrics


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = connect(db_path)
    yield connection
    connection.close()


def _seed_metrics(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO processing_metrics "
        "(file_type, document_count, avg_duration_seconds, avg_peak_memory_mb, "
        "avg_cpu_percent, updated_at) VALUES ('pdf', 2, 5.0, 100.0, 10.0, ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO confidence_metrics "
        "(file_type, process_type, page_count, avg_confidence, updated_at) "
        "VALUES ('pdf', 'native', 3, 1.0, ?)",
        (now,),
    )
    conn.commit()


def test_get_processing_metrics_returns_rows(conn: sqlite3.Connection):
    _seed_metrics(conn)

    metrics = get_processing_metrics(conn)

    assert len(metrics) == 1
    assert metrics[0].file_type == "pdf"
    assert metrics[0].document_count == 2
    assert metrics[0].avg_duration_seconds == pytest.approx(5.0)


def test_get_confidence_metrics_returns_rows(conn: sqlite3.Connection):
    _seed_metrics(conn)

    metrics = get_confidence_metrics(conn)

    assert len(metrics) == 1
    assert metrics[0].file_type == "pdf"
    assert metrics[0].process_type == "native"
    assert metrics[0].page_count == 3
    assert metrics[0].avg_confidence == pytest.approx(1.0)


def test_get_metrics_empty_when_no_data(conn: sqlite3.Connection):
    assert get_processing_metrics(conn) == []
    assert get_confidence_metrics(conn) == []


def test_reset_metrics_clears_both_tables(conn: sqlite3.Connection):
    _seed_metrics(conn)

    reset_metrics(conn)

    assert get_processing_metrics(conn) == []
    assert get_confidence_metrics(conn) == []
