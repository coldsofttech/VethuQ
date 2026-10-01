import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import vethuq_core.ocr as ocr_module
from vethuq_core.db import Db
from vethuq_core.ocr import _auto_worker_count, resolve_thread_workers, run_ocr_batch
from vethuq_core.settings import IndexSettings
from vethuq_core.source import Sources


@pytest.fixture
def conn(tmp_path):
    # check_same_thread=False: `run_ocr_batch` with workers > 1 hands this
    # connection to worker threads, same as `_run_worker` does for real.
    db_path = tmp_path / "vethuq.db"
    connection = Db.connect(db_path, check_same_thread=False)
    yield connection
    connection.close()


def _fake_ocr_result(text: str = "hello world", score: float = 0.95):
    return [{"rec_texts": [text], "rec_scores": [score]}]


def test_resolve_thread_workers_disabled_by_default(conn: sqlite3.Connection):
    assert resolve_thread_workers(conn, {"pdf": 0, "image": 5}) == 0


def test_resolve_thread_workers_fixed_value_capped_to_pending_count(conn: sqlite3.Connection):
    IndexSettings.set_thread_workers(conn, "8")

    assert resolve_thread_workers(conn, {"pdf": 0, "image": 3}) == 3


def test_resolve_thread_workers_fixed_value_unaffected_by_zero_pending(conn: sqlite3.Connection):
    IndexSettings.set_thread_workers(conn, "4")

    assert resolve_thread_workers(conn, {"pdf": 0, "image": 0}) == 4


@patch("vethuq_core.ocr.psutil.virtual_memory")
@patch("vethuq_core.ocr.psutil.cpu_percent")
@patch("vethuq_core.ocr.psutil.cpu_count")
def test_auto_worker_count_scales_down_when_cpu_busy(
    mock_cpu_count, mock_cpu_percent, mock_virtual_memory
):
    mock_cpu_count.return_value = 8
    mock_cpu_percent.return_value = 90.0
    mock_virtual_memory.return_value = MagicMock(percent=20.0, available=8 * 1024 * 1024 * 1024)

    assert _auto_worker_count({"pdf": 0, "image": 10}, 10) == 1


@patch("vethuq_core.ocr.psutil.virtual_memory")
@patch("vethuq_core.ocr.psutil.cpu_percent")
@patch("vethuq_core.ocr.psutil.cpu_count")
def test_auto_worker_count_scales_down_when_memory_scarce(
    mock_cpu_count, mock_cpu_percent, mock_virtual_memory
):
    mock_cpu_count.return_value = 8
    mock_cpu_percent.return_value = 10.0
    mock_virtual_memory.return_value = MagicMock(
        percent=20.0,
        available=500 * 1024 * 1024,  # under one engine's footprint
    )

    assert _auto_worker_count({"pdf": 0, "image": 10}, 10) == 1


@patch("vethuq_core.ocr.psutil.virtual_memory")
@patch("vethuq_core.ocr.psutil.cpu_percent")
@patch("vethuq_core.ocr.psutil.cpu_count")
def test_auto_worker_count_capped_at_pending_file_count(
    mock_cpu_count, mock_cpu_percent, mock_virtual_memory
):
    mock_cpu_count.return_value = 16
    mock_cpu_percent.return_value = 5.0
    mock_virtual_memory.return_value = MagicMock(percent=10.0, available=32 * 1024 * 1024 * 1024)

    assert _auto_worker_count({"pdf": 0, "image": 2}, 2) == 2


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_batch_orders_files_by_basename_across_sources(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    first = tmp_path / "zzz_source"
    first.mkdir()
    (first / "b_report.png").write_bytes(b"first bytes")
    second = tmp_path / "aaa_source"
    second.mkdir()
    (second / "a_report.png").write_bytes(b"second bytes")

    source_a = Sources.add(conn, first)
    source_b = Sources.add(conn, second)

    seen_order: list[str] = []
    run_ocr_batch(
        conn,
        [source_a, source_b],
        workers=1,
        on_file_done=lambda path, succeeded: seen_order.append(Path(path).name),
    )

    assert seen_order == ["a_report.png", "b_report.png"]


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_batch_processes_every_pending_file_with_multiple_workers(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    for name in ("a.png", "b.png", "c.png", "d.png"):
        (folder / name).write_bytes(f"bytes for {name}".encode())
    source = Sources.add(conn, folder)

    processed = run_ocr_batch(conn, [source], workers=4)

    assert len(processed) == 4
    docs = conn.execute("SELECT status FROM document_index").fetchall()
    assert all(doc["status"] == "indexed" for doc in docs)
    updated_source = conn.execute(
        "SELECT status FROM sources WHERE id = ?", (source.id,)
    ).fetchone()
    assert updated_source["status"] == "indexed"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_batch_stops_early_leaves_rest_untouched(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        (folder / name).write_bytes(f"bytes for {name}".encode())
    source = Sources.add(conn, folder)

    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    processed = run_ocr_batch(conn, [source], workers=1, should_stop=should_stop)

    assert [Path(p).name for p in processed] == ["a.png"]


@patch("vethuq_core.ocr._get_engine")
@patch("vethuq_core.ocr.psutil.virtual_memory")
@patch("vethuq_core.ocr.psutil.cpu_percent")
@patch("vethuq_core.ocr.psutil.cpu_count")
def test_run_ocr_batch_auto_re_resolves_workers_after_each_file(
    mock_cpu_count,
    mock_cpu_percent,
    mock_virtual_memory,
    mock_get_engine,
    conn: sqlite3.Connection,
    tmp_path,
):
    mock_cpu_count.return_value = 8
    mock_cpu_percent.return_value = 5.0
    mock_virtual_memory.return_value = MagicMock(percent=10.0, available=32 * 1024 * 1024 * 1024)
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    file_names = ("a.png", "b.png", "c.png", "d.png", "e.png")
    for name in file_names:
        (folder / name).write_bytes(f"bytes for {name}".encode())
    source = Sources.add(conn, folder)
    IndexSettings.set_thread_workers(conn, "auto")

    with patch.object(
        ocr_module, "resolve_thread_workers", wraps=ocr_module.resolve_thread_workers
    ) as spy_resolve:
        processed = run_ocr_batch(conn, [source], workers=1)

    assert len(processed) == len(file_names)
    docs = conn.execute("SELECT status FROM document_index").fetchall()
    assert all(doc["status"] == "indexed" for doc in docs)
    # Once per finished file except the last (nothing left to size workers
    # for by then), not just once up front for the whole run.
    assert spy_resolve.call_count == len(file_names) - 1
