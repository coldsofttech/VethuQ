import logging
import sqlite3
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from conftest import PaddleStub
from vethuq_core.logs import Logs
from vethuq_core.ocr import Deepening, Ocr
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage


def _write_png(path: Path, width: int = 40) -> None:
    # Distinct widths give distinct bytes - identical files are skipped as duplicates.
    cv2.imwrite(str(path), np.full((20, width, 3), 255, dtype=np.uint8))


def _result(*lines: str, score: float = 0.9):
    return [{"rec_texts": list(lines), "rec_scores": [score] * len(lines)}]


def _image_page(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    return conn.execute(
        "SELECT p.* FROM image_pages p JOIN document_index d ON d.id = p.document_id "
        "WHERE d.file_path LIKE ?",
        (f"%{name}",),
    ).fetchone()


class TestOcr:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_quick_engine_reads_each_file_once(
        self, mock_get_engine, conn, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _result("hello")
        mock_get_engine.return_value = engine
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(storage, folder)

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        assert engine.predict.call_count == 1
        page = _image_page(conn, "a.png")
        assert (page["ocr_phase"], page["ocr_angles"]) == (1, "0")

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_moderate_engine_adds_rotated_text_and_records_progress(
        self, mock_get_engine, conn, storage: Storage, tmp_path
    ):
        # Quick read finds one line; every rotated read finds the same extra one.
        engine = PaddleStub()
        engine.predict.side_effect = lambda image: (
            _result("hello") if isinstance(image, str) else _result("DIRECTOR", "hello")
        )
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(storage, "moderate")
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(storage, folder)

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        page = _image_page(conn, "a.png")
        assert page["ocr_text"].split("\n") == ["hello", "DIRECTOR"]
        assert (page["ocr_phase"], page["ocr_angles"]) == (2, "0,90,180,270")
        assert engine.predict.call_count == 1 + len(Deepening.PHASE_ANGLES[2])

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_logs_each_angle_before_reading_it(
        self, mock_get_engine, conn, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _result("hello")
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(storage, "moderate")
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(storage, folder)
        messages: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                messages.append(record.getMessage())

        logger = Logs.get_logger("index")
        handler = Capture()
        # The logger only has a level once `Logs.setup` has run for it; without one the
        # info-level reads would be dropped and this would depend on test order.
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        reads = [m for m in messages if m.startswith("Deeper read:")]
        assert [m.rsplit("angle=", 1)[1] for m in reads] == ["90", "180", "270"]
        assert all("a.png" in m and "phase=2" in m for m in reads)

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_deep_engine_reads_every_angle_and_is_not_repeated(
        self, mock_get_engine, conn, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _result("hello")
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(storage, "deep")
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(storage, folder)

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
        assert _image_page(conn, "a.png")["ocr_phase"] == 3
        assert engine.predict.call_count == 360 // 15

        # Already at the deepest phase: a second run has nothing left to read.
        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
        assert engine.predict.call_count == 360 // 15

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_raising_engine_setting_deepens_already_indexed_files(
        self, mock_get_engine, conn, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _result("hello")
        mock_get_engine.return_value = engine
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(storage, folder)
        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
        assert engine.predict.call_count == 1

        OcrSettings.set_engine(storage, "moderate")
        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        assert _image_page(conn, "a.png")["ocr_phase"] == 2
        # Only the new angles were read - the quick pass wasn't redone.
        assert engine.predict.call_count == 1 + len(Deepening.PHASE_ANGLES[2])

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_new_file_gets_its_quick_pass_before_deeper_work_resumes(
        self, mock_get_engine, conn, storage: Storage, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(Deepening, "QUICK_WORK_CHECK_SECONDS", 0.0)
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        calls: list[str] = []

        def predict(image):
            calls.append(Path(image).name if isinstance(image, str) else "angle")
            # Right after the first rotated pass, a new file shows up in the source.
            if calls == ["a.png", "angle"]:
                _write_png(folder / "b.png", width=50)
            return _result("hello")

        engine = PaddleStub()
        engine.predict.side_effect = predict
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(storage, "moderate")
        source = Sources.add(storage, folder)

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        # a.png quick, one angle of a.png, then b.png's quick pass jumps the queue.
        assert calls[:3] == ["a.png", "angle", "b.png"], calls
        # Nothing was lost: both files end up fully moderate-indexed.
        assert _image_page(conn, "a.png")["ocr_angles"] == "0,90,180,270"
        assert _image_page(conn, "b.png")["ocr_angles"] == "0,90,180,270"

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_modified_file_gets_its_quick_pass_before_deeper_work_resumes(
        self, mock_get_engine, conn, storage: Storage, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(Deepening, "QUICK_WORK_CHECK_SECONDS", 0.0)
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        _write_png(folder / "b.png", width=50)
        calls: list[str] = []

        def predict(image):
            calls.append(Path(image).name if isinstance(image, str) else "angle")
            # Right after the first rotated pass - when both files already had their quick
            # pass this run - b.png is edited in place.
            if calls == ["a.png", "b.png", "angle"]:
                _write_png(folder / "b.png", width=60)
            return _result("hello")

        engine = PaddleStub()
        engine.predict.side_effect = predict
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(storage, "moderate")
        source = Sources.add(storage, folder)

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        # The edited b.png jumps the queue: re-read quickly before any more angle passes.
        assert calls[:4] == ["a.png", "b.png", "angle", "b.png"], calls
        assert _image_page(conn, "b.png")["ocr_angles"] == "0,90,180,270"

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_failed_file_is_not_retried_by_later_rounds(
        self, mock_get_engine, storage: Storage, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.side_effect = RuntimeError("boom")
        mock_get_engine.return_value = engine
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "bad.png")
        source = Sources.add(storage, folder)
        attempts = 1 + 3  # first try plus the default retries

        processed = Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        assert len(processed) == 1
        assert engine.predict.call_count == attempts
