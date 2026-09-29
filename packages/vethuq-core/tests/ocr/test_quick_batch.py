import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import PaddleStub
from vethuq_core.ocr import Quick, Scheduler
from vethuq_core.settings import IndexSettings
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage


def _fake_ocr_result(text: str = "hello world", score: float = 0.95):
    return [{"rec_texts": [text], "rec_scores": [score]}]


class TestQuickBatch:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_run_ocr_batch_orders_files_by_basename_across_sources(
        self, mock_get_engine, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        first = tmp_path / "zzz_source"
        first.mkdir()
        (first / "b_report.png").write_bytes(b"first bytes")
        second = tmp_path / "aaa_source"
        second.mkdir()
        (second / "a_report.png").write_bytes(b"second bytes")

        source_a = Sources.add(storage, first)
        source_b = Sources.add(storage, second)

        seen_order: list[str] = []
        Quick.run_batch(
            storage,
            [source_a, source_b],
            workers=1,
            on_file_done=lambda path, succeeded: seen_order.append(Path(path).name),
        )

        assert seen_order == ["a_report.png", "b_report.png"]

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_run_ocr_batch_processes_every_pending_file_with_multiple_workers(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        for name in ("a.png", "b.png", "c.png", "d.png"):
            (folder / name).write_bytes(f"bytes for {name}".encode())
        source = Sources.add(storage, folder)

        processed = Quick.run_batch(storage, [source], workers=4)

        assert len(processed) == 4
        docs = conn.execute("SELECT status FROM document_index").fetchall()
        assert all(doc["status"] == "indexed" for doc in docs)
        updated_source = conn.execute(
            "SELECT status FROM sources WHERE id = ?", (source.id,)
        ).fetchone()
        assert updated_source["status"] == "indexed"

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_run_ocr_batch_skips_file_already_claimed_by_another_run(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        claimed_path = folder / "a.png"
        free_path = folder / "b.png"
        claimed_path.write_bytes(b"bytes for a")
        free_path.write_bytes(b"bytes for b")
        source = Sources.add(storage, folder)

        now = "2026-01-01T00:00:00+00:00"
        other_run_document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (now,)
        ).lastrowid
        conn.execute(
            "INSERT INTO document_index "
            "(source_id, document_id, file_path, file_type, status, started_at) "
            "VALUES (?, ?, ?, 'image', 'processing', ?)",
            (source.id, other_run_document_id, str(claimed_path.resolve()), now),
        )
        conn.commit()

        done_results: dict[str, bool | None] = {}
        processed = Quick.run_batch(
            storage,
            [source],
            workers=1,
            on_file_done=lambda path, succeeded: done_results.__setitem__(
                Path(path).name, succeeded
            ),
        )

        # Only the unclaimed file is actually (re)processed by this run.
        assert [Path(p).name for p in processed] == ["b.png"]
        # `on_file_done` still fires for the claimed file (e.g. so a caller
        # tracking in-flight files clears it), but with None rather than a bool.
        assert done_results == {"a.png": None, "b.png": True}

        claimed = conn.execute(
            "SELECT status, document_id FROM document_index WHERE file_path = ?",
            (str(claimed_path.resolve()),),
        ).fetchone()
        assert claimed["status"] == "processing"
        assert claimed["document_id"] == other_run_document_id
        engine.predict.assert_called_once()

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_run_ocr_batch_stops_early_leaves_rest_untouched(
        self, mock_get_engine, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        for name in ("a.png", "b.png", "c.png"):
            (folder / name).write_bytes(f"bytes for {name}".encode())
        source = Sources.add(storage, folder)

        calls = {"n": 0}

        def should_stop() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        processed = Quick.run_batch(storage, [source], workers=1, should_stop=should_stop)

        assert [Path(p).name for p in processed] == ["a.png"]

    @patch("vethuq_core.ocr.engines.Engines.get")
    @patch("vethuq_core.ocr.scheduler.psutil.virtual_memory")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_percent")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_count")
    def test_run_ocr_batch_auto_re_resolves_workers_after_each_file(
        self,
        mock_cpu_count,
        mock_cpu_percent,
        mock_virtual_memory,
        mock_get_engine,
        conn: sqlite3.Connection,
        storage: Storage,
        tmp_path,
    ):
        mock_cpu_count.return_value = 8
        mock_cpu_percent.return_value = 5.0
        # `total` is needed too: `Scheduler.would_exceed_budget` divides by it once a
        # file has produced a metrics row, and an unset attribute is a MagicMock.
        mock_virtual_memory.return_value = MagicMock(
            percent=10.0,
            available=32 * 1024 * 1024 * 1024,
            total=64 * 1024 * 1024 * 1024,
        )
        engine = PaddleStub()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine

        folder = tmp_path / "docs"
        folder.mkdir()
        file_names = ("a.png", "b.png", "c.png", "d.png", "e.png")
        for name in file_names:
            (folder / name).write_bytes(f"bytes for {name}".encode())
        source = Sources.add(storage, folder)
        IndexSettings.set_thread_workers(storage, "auto")

        with patch.object(
            Scheduler, "resolve_workers", wraps=Scheduler.resolve_workers
        ) as spy_resolve:
            processed = Quick.run_batch(storage, [source], workers=1)

        assert len(processed) == len(file_names)
        docs = conn.execute("SELECT status FROM document_index").fetchall()
        assert all(doc["status"] == "indexed" for doc in docs)
        # Once per finished file except the last (nothing left to size workers
        # for by then), not just once up front for the whole run.
        assert spy_resolve.call_count == len(file_names) - 1

    @patch("vethuq_core.ocr.quick.Metrics.update_confidence")
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_run_ocr_batch_rolls_back_pages_and_status_if_a_later_write_fails(
        self,
        mock_get_engine,
        mock_update_confidence,
        conn: sqlite3.Connection,
        storage: Storage,
        tmp_path,
    ):
        """Same atomicity guarantee as `Quick.run`, exercised through `Quick.process_file`."""
        engine = PaddleStub()
        engine.predict.return_value = _fake_ocr_result()
        mock_get_engine.return_value = engine
        mock_update_confidence.side_effect = RuntimeError("boom")

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(storage, image_path)

        with pytest.raises(RuntimeError, match="boom"):
            Quick.run_batch(storage, [source], workers=1)

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
        ).fetchone()
        assert doc["status"] == "processing"
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM image_pages WHERE document_id = ?", (doc["id"],)
            ).fetchone()["n"]
            == 0
        )
        assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
