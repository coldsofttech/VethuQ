import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from vethuq_core.db import Db
from vethuq_core.ocr import Deepening, Document, Ocr
from vethuq_core.settings import InvalidSettingValueError, OcrSettings
from vethuq_core.source import Sources


@pytest.fixture
def conn(tmp_path):
    connection = Db.connect(tmp_path / "vethuq.db", check_same_thread=False)
    yield connection
    connection.close()


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


def test_ocr_engine_defaults_to_quick_and_validates(conn: sqlite3.Connection):
    assert OcrSettings.get_engine(conn) == "quick"

    OcrSettings.set_engine(conn, "deep")
    assert OcrSettings.get_engine(conn) == "deep"

    with pytest.raises(InvalidSettingValueError):
        OcrSettings.set_engine(conn, "thorough")


def test_phase_angles_cover_every_15_degrees_once():
    all_angles = [
        angle for phase in sorted(Deepening.PHASE_ANGLES) for angle in Deepening.PHASE_ANGLES[phase]
    ]

    assert sorted(all_angles) == list(range(0, 360, 15))


def test_completed_phase_needs_every_angle_in_order():
    assert Deepening.completed_phase({0}) == 1
    assert Deepening.completed_phase({0, 90, 180}) == 1
    assert Deepening.completed_phase({0, 90, 180, 270}) == 2
    assert Deepening.completed_phase(set(range(0, 360, 15))) == 3
    assert Deepening.completed_phase({15, 30}) == 0


def test_merge_lines_skips_known_text_and_keeps_fuller_word():
    merged, added = Deepening.merge_lines("Invoice\nSECRETAR", ["invoice", "SECRETARY", "DIRECTOR"])

    assert merged.split("\n") == ["Invoice", "SECRETARY", "DIRECTOR"]
    assert added == [1, 2]  # indexes into the new lines: "invoice" (index 0) was already known


def test_rotate_array_right_angles_swap_dimensions_and_others_grow():
    array = np.zeros((20, 40, 3), dtype=np.uint8)

    assert Deepening.rotate_array(array, 90).shape[:2] == (40, 20)
    assert Deepening.rotate_array(array, 180).shape[:2] == (20, 40)
    rotated = Deepening.rotate_array(array, 45)
    assert rotated.shape[0] > 20 and rotated.shape[1] > 20


def test_migration_adds_phase_columns_to_existing_pages(tmp_path):
    db_path = tmp_path / "old.db"
    old = sqlite3.connect(db_path)
    old.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (16);
        CREATE TABLE image_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
            ocr_text TEXT NOT NULL, confidence REAL NOT NULL, ocr_engine TEXT,
            language TEXT, image_width INTEGER, image_height INTEGER
        );
        INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (1, 'hi', 0.9);
        """
    )
    old.commit()
    old.close()

    migrated = Db.connect(db_path)
    try:
        row = migrated.execute("SELECT ocr_phase, ocr_angles FROM image_pages").fetchone()
        assert (row["ocr_phase"], row["ocr_angles"]) == (1, "0")
    finally:
        migrated.close()


@patch("vethuq_core.ocr.Engine.get")
def test_quick_engine_reads_each_file_once(mock_get_engine, conn, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = _result("hello")
    mock_get_engine.return_value = engine
    folder = tmp_path / "src"
    folder.mkdir()
    _write_png(folder / "a.png")
    source = Sources.add(conn, folder)

    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

    assert engine.predict.call_count == 1
    page = _image_page(conn, "a.png")
    assert (page["ocr_phase"], page["ocr_angles"]) == (1, "0")


@patch("vethuq_core.ocr.Engine.get")
def test_moderate_engine_adds_rotated_text_and_records_progress(mock_get_engine, conn, tmp_path):
    # Quick read finds one line; every rotated read finds the same extra one.
    engine = MagicMock()
    engine.predict.side_effect = lambda image: (
        _result("hello") if isinstance(image, str) else _result("DIRECTOR", "hello")
    )
    mock_get_engine.return_value = engine
    OcrSettings.set_engine(conn, "moderate")
    folder = tmp_path / "src"
    folder.mkdir()
    _write_png(folder / "a.png")
    source = Sources.add(conn, folder)

    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

    page = _image_page(conn, "a.png")
    assert page["ocr_text"].split("\n") == ["hello", "DIRECTOR"]
    assert (page["ocr_phase"], page["ocr_angles"]) == (2, "0,90,180,270")
    assert engine.predict.call_count == 1 + len(Deepening.PHASE_ANGLES[2])


@patch("vethuq_core.ocr.Engine.get")
def test_deep_engine_reads_every_angle_and_is_not_repeated(mock_get_engine, conn, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = _result("hello")
    mock_get_engine.return_value = engine
    OcrSettings.set_engine(conn, "deep")
    folder = tmp_path / "src"
    folder.mkdir()
    _write_png(folder / "a.png")
    source = Sources.add(conn, folder)

    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])
    assert _image_page(conn, "a.png")["ocr_phase"] == 3
    assert engine.predict.call_count == 360 // 15

    # Already at the deepest phase: a second run has nothing left to read.
    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])
    assert engine.predict.call_count == 360 // 15


@patch("vethuq_core.ocr.Engine.get")
def test_raising_engine_setting_deepens_already_indexed_files(mock_get_engine, conn, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = _result("hello")
    mock_get_engine.return_value = engine
    folder = tmp_path / "src"
    folder.mkdir()
    _write_png(folder / "a.png")
    source = Sources.add(conn, folder)
    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])
    assert engine.predict.call_count == 1

    OcrSettings.set_engine(conn, "moderate")
    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

    assert _image_page(conn, "a.png")["ocr_phase"] == 2
    # Only the new angles were read - the quick pass wasn't redone.
    assert engine.predict.call_count == 1 + len(Deepening.PHASE_ANGLES[2])


@patch("vethuq_core.ocr.Engine.get")
def test_new_file_gets_its_quick_pass_before_deeper_work_resumes(
    mock_get_engine, conn, tmp_path, monkeypatch
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

    engine = MagicMock()
    engine.predict.side_effect = predict
    mock_get_engine.return_value = engine
    OcrSettings.set_engine(conn, "moderate")
    source = Sources.add(conn, folder)

    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

    # a.png quick, one angle of a.png, then b.png's quick pass jumps the queue.
    assert calls[:3] == ["a.png", "angle", "b.png"], calls
    # Nothing was lost: both files end up fully moderate-indexed.
    assert _image_page(conn, "a.png")["ocr_angles"] == "0,90,180,270"
    assert _image_page(conn, "b.png")["ocr_angles"] == "0,90,180,270"


@patch("vethuq_core.ocr.Engine.get")
def test_failed_file_is_not_retried_by_later_rounds(mock_get_engine, conn, tmp_path):
    engine = MagicMock()
    engine.predict.side_effect = RuntimeError("boom")
    mock_get_engine.return_value = engine
    folder = tmp_path / "src"
    folder.mkdir()
    _write_png(folder / "bad.png")
    source = Sources.add(conn, folder)
    attempts = 1 + 3  # first try plus the default retries

    processed = Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

    assert len(processed) == 1
    assert engine.predict.call_count == attempts


def test_deepening_units_order_moderate_before_deep_and_skip_native(conn, tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    source = Sources.add(conn, folder)
    for index, (phase, page_source) in enumerate([(2, "ocr"), (1, "ocr"), (1, "native")], start=1):
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


def test_migration_renames_old_setting_keys_keeping_values(tmp_path):
    db_path = tmp_path / "old.db"
    old = sqlite3.connect(db_path)
    old.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (17);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings (key, value) VALUES
            ('thread_workers', '4'),
            ('stale_lock', 'disable'),
            ('ocr_engine', 'deep'),
            ('index_ocr_retry_attempts', '9'),
            ('ocr_retry_attempts', '1'),
            ('gpu_enabled', 'true');
        """
    )
    old.commit()
    old.close()

    migrated = Db.connect(db_path)
    try:
        settings = {
            row["key"]: row["value"] for row in migrated.execute("SELECT key, value FROM settings")
        }
    finally:
        migrated.close()

    assert settings == {
        "index_thread_workers": "4",
        "index_stale_lock": "disable",
        "index_engine": "deep",
        "index_ocr_retry_attempts": "9",  # the already-present new key wins
        "gpu_enabled": "true",
    }


def test_deepening_progress_counts_pages_done_per_phase(conn, tmp_path):

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


def test_native_pages_are_stored_at_the_quick_phase_and_migrated_there(tmp_path):
    from vethuq_core.ocr import PageResult

    assert PageResult("text", 1.0, "native").phase_columns() == (1, "")
    assert PageResult("text", 0.9, "ocr").phase_columns() == (1, "0")

    db_path = tmp_path / "v18.db"
    setup = Db.connect(db_path)
    folder = tmp_path / "src"
    folder.mkdir()
    source = Sources.add(setup, folder)
    setup.execute("INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01')")
    setup.execute(
        "INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status) "
        "VALUES (1, ?, 1, 'x.pdf', 'pdf', 'indexed')",
        (source.id,),
    )
    setup.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source, "
        "ocr_phase, ocr_angles) VALUES (1, 1, 'x', 1.0, 'native', 3, '')"
    )
    setup.execute("UPDATE schema_version SET version = 18")
    setup.commit()
    setup.close()

    migrated = Db.connect(db_path)
    try:
        assert migrated.execute("SELECT ocr_phase FROM pdf_pages").fetchone()["ocr_phase"] == 1
    finally:
        migrated.close()


def _scored(*lines: tuple[str, float]):
    return [{"rec_texts": [t for t, _ in lines], "rec_scores": [sc for _, sc in lines]}]


@patch("vethuq_core.ocr.Engine.get")
def test_deeper_phases_track_timestamps_and_their_own_metrics(mock_get_engine, conn, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = _result("hello")
    mock_get_engine.return_value = engine
    OcrSettings.set_engine(conn, "deep")
    folder = tmp_path / "src"
    folder.mkdir()
    _write_png(folder / "a.png")
    source = Sources.add(conn, folder)

    Ocr.run_phased(conn, lambda: [Sources.get(conn, source.id)])

    phases = {
        row["phase"]: row for row in conn.execute("SELECT * FROM document_phases ORDER BY phase")
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


@patch("vethuq_core.ocr.Engine.get")
def test_interrupted_phase_is_not_completed_or_folded_until_finished(
    mock_get_engine, conn, tmp_path, monkeypatch
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

    engine = MagicMock()
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
        conn.execute("SELECT COUNT(*) FROM processing_metrics WHERE phase = 2").fetchone()[0] == 0
    )


@patch("vethuq_core.ocr.Engine.get")
def test_reindexing_a_changed_file_clears_its_deeper_phase_tracking(
    mock_get_engine, conn, tmp_path
):
    engine = MagicMock()
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


@patch("vethuq_core.ocr.Engine.get")
def test_page_confidence_is_weighted_by_lines_added_in_deeper_phases(
    mock_get_engine, conn, tmp_path
):
    engine = MagicMock()
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


def test_migration_v20_makes_existing_processing_metrics_phase_1(tmp_path):
    db_path = tmp_path / "v19.db"
    setup = Db.connect(db_path)
    setup.execute("DROP TABLE processing_metrics")
    setup.execute(
        "CREATE TABLE processing_metrics (file_type TEXT NOT NULL, size_bucket TEXT NOT NULL, "
        "document_count INTEGER NOT NULL DEFAULT 0, avg_duration_seconds REAL NOT NULL DEFAULT 0, "
        "avg_peak_memory_mb REAL NOT NULL DEFAULT 0, avg_cpu_percent REAL NOT NULL DEFAULT 0, "
        "updated_at TEXT NOT NULL, PRIMARY KEY (file_type, size_bucket))"
    )
    setup.execute("INSERT INTO processing_metrics VALUES ('pdf', 'small', 4, 2.5, 100, 10, 'now')")
    setup.execute("UPDATE schema_version SET version = 19")
    setup.commit()
    setup.close()

    migrated = Db.connect(db_path)
    try:
        row = migrated.execute("SELECT * FROM processing_metrics").fetchone()
        assert (row["phase"], row["document_count"], row["avg_duration_seconds"]) == (1, 4, 2.5)
    finally:
        migrated.close()
