import sqlite3
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest
from conftest import PaddleStub
from vethuq_core.ocr import Deepening, Document, Ocr
from vethuq_core.settings import OcrSettings
from vethuq_core.source import Sources


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


def _scored(*lines: tuple[str, float]):
    return [{"rec_texts": [t for t, _ in lines], "rec_scores": [sc for _, sc in lines]}]


class TestDeepening:
    def test_max_phase_follows_the_engine_setting(self, conn):
        assert Deepening.max_phase(conn) == 1
        OcrSettings.set_engine(conn, "moderate")
        assert Deepening.max_phase(conn) == 2
        OcrSettings.set_engine(conn, "deep")
        assert Deepening.max_phase(conn) == 3
        assert Deepening.PHASE_NAMES == {1: "quick", 2: "moderate", 3: "deep"}

    def test_phase_angles_cover_every_15_degrees_once(self):
        all_angles = [
            angle
            for phase in sorted(Deepening.PHASE_ANGLES)
            for angle in Deepening.PHASE_ANGLES[phase]
        ]

        assert sorted(all_angles) == list(range(0, 360, 15))

    def test_completed_phase_needs_every_angle_in_order(self):
        assert Deepening.completed_phase({0}) == 1
        assert Deepening.completed_phase({0, 90, 180}) == 1
        assert Deepening.completed_phase({0, 90, 180, 270}) == 2
        assert Deepening.completed_phase(set(range(0, 360, 15))) == 3
        assert Deepening.completed_phase({15, 30}) == 0

    def test_merge_lines_skips_known_text_and_keeps_fuller_word(self):
        merged, added = Deepening.merge_lines(
            "Invoice\nSECRETAR", ["invoice", "SECRETARY", "DIRECTOR"]
        )

        assert merged.split("\n") == ["Invoice", "SECRETARY", "DIRECTOR"]
        assert added == [1, 2]  # indexes into the new lines: "invoice" (index 0) was already known

    def test_rotate_array_right_angles_swap_dimensions_and_others_grow(self):
        array = np.zeros((20, 40, 3), dtype=np.uint8)

        assert Deepening.rotate_array(array, 90).shape[:2] == (40, 20)
        assert Deepening.rotate_array(array, 180).shape[:2] == (20, 40)
        rotated = Deepening.rotate_array(array, 45)
        assert rotated.shape[0] > 20 and rotated.shape[1] > 20

    def test_deepening_units_order_moderate_before_deep_and_skip_native(self, conn, tmp_path):
        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(conn, folder)
        for index, (phase, page_source) in enumerate(
            [(2, "ocr"), (1, "ocr"), (1, "native")], start=1
        ):
            document_id = conn.execute(
                "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
            ).lastrowid
            conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (?, ?, ?, 'pdf', 'indexed')",
                (source.id, document_id, str(folder / f"{index}.pdf")),
            )
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source, "
                "ocr_phase, ocr_angles) VALUES (?, 1, 'x', 0.9, ?, ?, '0')",
                (index, page_source, phase),
            )
        conn.commit()

        units = Deepening.find_units(conn, [source], max_phase=3)

        # The phase-1 page (next: moderate) goes before the phase-2 one (next: deep);
        # the native-text page has nothing to read.
        assert [(unit.document_id, unit.phase) for unit in units] == [(2, 2), (1, 3)]
        assert Deepening.find_units(conn, [source], max_phase=1) == []

    def test_deepening_progress_counts_pages_done_per_phase(self, conn, tmp_path):

        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(conn, folder)
        for index, (phase, page_source) in enumerate(
            [(1, "ocr"), (2, "ocr"), (3, "ocr"), (1, "native")], start=1
        ):
            document_id = conn.execute(
                "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
            ).lastrowid
            conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (?, ?, ?, 'pdf', 'indexed')",
                (source.id, document_id, str(folder / f"{index}.pdf")),
            )
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source, "
                "ocr_phase, ocr_angles) VALUES (?, 1, 'x', 0.9, ?, ?, '0')",
                (index, page_source, phase),
            )
        conn.commit()

        # The native page isn't counted; of the three OCR pages, 2 reached moderate, 1 deep.
        assert Deepening.progress(conn, [source], 3) == {2: (2, 3), 3: (1, 3)}
        assert Deepening.progress(conn, [source], 2) == {2: (2, 3)}
        assert Deepening.progress(conn, [source], 1) == {}

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_deeper_phases_track_timestamps_and_their_own_metrics(
        self, mock_get_engine, conn, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _result("hello")
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(conn, "deep")
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(conn, folder)

        Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

        phases = {
            row["phase"]: row
            for row in conn.execute("SELECT * FROM document_phases ORDER BY phase")
        }
        assert sorted(phases) == [2, 3]
        for row in phases.values():
            assert row["started_at"] and row["completed_at"] and row["indexed_at"]
            assert row["started_at"] <= row["completed_at"]
            assert row["duration_seconds"] > 0
        # Each phase has its own averages, alongside the quick pass's - not blended into it.
        metrics = {
            row["phase"]: row["document_count"]
            for row in conn.execute("SELECT phase, document_count FROM processing_metrics")
        }
        assert metrics == {1: 1, 2: 1, 3: 1}

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_interrupted_phase_is_not_completed_or_folded_until_finished(
        self, mock_get_engine, conn, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(Deepening, "QUICK_WORK_CHECK_SECONDS", 0.0)
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        calls = {"n": 0}

        def predict(image):
            calls["n"] += 1
            if calls["n"] == 2:  # right after the first rotated pass
                _write_png(folder / "b.png", width=50)
            return _result("hello")

        engine = PaddleStub()
        engine.predict.side_effect = predict
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(conn, "moderate")
        source = Sources.add(conn, folder)
        stop_after = {"pending": False}

        # Stop the run as soon as the new file has had its quick pass.
        def should_stop() -> bool:
            return stop_after["pending"] and _image_page(conn, "b.png") is not None

        stop_after["pending"] = True
        Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)], should_stop=should_stop)

        a_row = conn.execute(
            "SELECT dp.* FROM document_phases dp "
            "JOIN document_index d ON d.document_id = dp.document_id "
            "WHERE d.file_path LIKE '%a.png' AND dp.phase = 2"
        ).fetchone()
        assert a_row is not None and a_row["started_at"]
        assert a_row["completed_at"] is None  # only part of its angles were read
        assert (
            conn.execute("SELECT COUNT(*) FROM processing_metrics WHERE phase = 2").fetchone()[0]
            == 0
        )

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_reindexing_a_changed_file_clears_its_deeper_phase_tracking(
        self, mock_get_engine, conn, tmp_path
    ):
        engine = PaddleStub()
        engine.predict.return_value = _result("hello")
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(conn, "moderate")
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(conn, folder)
        Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])
        assert conn.execute("SELECT COUNT(*) FROM document_phases").fetchone()[0] == 1

        _write_png(folder / "a.png", width=60)  # content changes
        Document.upsert(conn, source.id, folder / "a.png", "image")

        assert conn.execute("SELECT COUNT(*) FROM document_phases").fetchone()[0] == 0

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_page_confidence_is_weighted_by_lines_added_in_deeper_phases(
        self, mock_get_engine, conn, tmp_path
    ):
        engine = PaddleStub()
        # Quick read: one line at 0.9. Every rotated read also finds DIRECTOR at 0.5.
        engine.predict.side_effect = lambda image: (
            _scored(("hello", 0.9))
            if isinstance(image, str)
            else _scored(("hello", 0.9), ("DIRECTOR", 0.5))
        )
        mock_get_engine.return_value = engine
        OcrSettings.set_engine(conn, "moderate")
        folder = tmp_path / "src"
        folder.mkdir()
        _write_png(folder / "a.png")
        source = Sources.add(conn, folder)

        Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

        # DIRECTOR is added once (later angles find it already there): (0.9 * 1 + 0.5) / 2.
        assert _image_page(conn, "a.png")["confidence"] == pytest.approx(0.7)
