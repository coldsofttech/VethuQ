import sqlite3

import pytest
from vethuq_core.db import Db
from vethuq_core.ocr.metrics import Metrics
from vethuq_core.stats import Confidence, Processing


def _fold(storage, language, duration, *, memory=100.0, cpu=10.0, phase=1):
    Metrics.fold_processing(
        storage,
        phase=phase,
        file_type="image",
        extension="png",
        file_size_bytes=1000,
        duration=duration,
        peak_memory_mb=memory,
        cpu_percent=cpu,
        language=language,
    )


class TestProcessingPerLanguage:
    def test_each_language_keeps_its_own_average(self, storage):
        _fold(storage, "en", 2.0)
        _fold(storage, "en", 4.0)
        _fold(storage, "te", 10.0)

        by_language = {m.language: m for m in Processing.get_metrics(storage)}

        assert by_language["en"].document_count == 2
        assert by_language["en"].avg_duration_seconds == pytest.approx(3.0)
        assert by_language["te"].document_count == 1
        assert by_language["te"].avg_duration_seconds == pytest.approx(10.0)

    def test_a_language_filter_returns_only_that_language(self, storage):
        _fold(storage, "en", 2.0)
        _fold(storage, "te", 10.0)

        assert [m.language for m in Processing.get_metrics(storage, "te")] == ["te"]

    def test_the_default_language_is_english(self, storage):
        Metrics.fold_processing(
            storage,
            phase=1,
            file_type="image",
            extension="png",
            file_size_bytes=1,
            duration=1.0,
            peak_memory_mb=1.0,
            cpu_percent=1.0,
        )

        assert [m.language for m in Processing.get_metrics(storage)] == ["en"]

    def test_the_memory_budget_averages_every_language(self, storage):
        _fold(storage, "en", 2.0, memory=100.0)
        _fold(storage, "te", 2.0, memory=300.0)

        row = storage.get_processing_metrics_budget_row(1, "png", "small")

        assert row["avg_peak_memory_mb"] == pytest.approx(200.0)

    def test_there_is_no_budget_row_without_history(self, storage):
        assert storage.get_processing_metrics_budget_row(1, "png", "small") is None

    def test_the_eta_average_weights_each_language_by_its_documents(self, storage):
        _fold(storage, "en", 2.0)
        _fold(storage, "en", 2.0)
        _fold(storage, "te", 8.0)

        rows = storage.get_processing_metrics_avg_duration_by_file_type(1)

        assert rows[0]["avg_duration_seconds"] == pytest.approx(4.0)


class TestConfidencePerLanguage:
    def test_languages_are_averaged_apart(self, storage):
        Metrics.fold_confidence(storage, "pdf", "pdf", "ocr", "en", [0.9, 0.9])
        Metrics.fold_confidence(storage, "pdf", "pdf", "ocr", "te", [0.6])
        Metrics.fold_confidence(storage, "pdf", "pdf", "ocr", "te", [0.8])

        by_language = {m.language: m for m in Confidence.get_metrics(storage)}

        assert by_language["en"].avg_confidence == pytest.approx(0.9)
        assert by_language["te"].page_count == 2
        assert by_language["te"].avg_confidence == pytest.approx(0.7)

    def test_a_language_filter_returns_only_that_language(self, storage):
        Metrics.fold_confidence(storage, "pdf", "pdf", "ocr", "en", [0.9])
        Metrics.fold_confidence(storage, "pdf", "pdf", "ocr", "te", [0.6])

        assert [m.language for m in Confidence.get_metrics(storage, "en")] == ["en"]

    def test_no_pages_records_nothing(self, storage):
        Metrics.fold_confidence(storage, "pdf", "pdf", "ocr", "te", [])

        assert Confidence.get_metrics(storage) == []

    def test_a_documents_pages_are_filed_under_the_language_each_was_read_in(self, conn, storage):
        conn.executescript(
            """
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/d', 'folder', 'indexed', 'x');
            INSERT INTO documents (created_at) VALUES ('x');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/d/a.pdf', 'pdf', 'indexed');
            INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source,
                                   language)
                VALUES (1, 1, 'a', 0.9, 'ocr', 'en'), (1, 2, 'b', 0.5, 'ocr', 'te'),
                       (1, 3, 'c', 0.7, 'ocr', 'te'), (1, 4, 'd', 0.8, 'ocr', NULL);
            """
        )

        Metrics.update_confidence(storage, 1, "pdf")

        by_language = {m.language: m for m in Confidence.get_metrics(storage)}
        assert by_language["te"].page_count == 2
        assert by_language["te"].avg_confidence == pytest.approx(0.6)
        assert by_language["en"].page_count == 2  # the explicit en page and the unrecorded one
        assert Metrics.document_language(storage, 1, "pdf") in {"en", "te"}

    def test_a_document_is_in_the_language_most_of_its_pages_were_read_in(self, conn, storage):
        conn.executescript(
            """
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/d', 'folder', 'indexed', 'x');
            INSERT INTO documents (created_at) VALUES ('x');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/d/a.pdf', 'pdf', 'indexed');
            INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source,
                                   language)
                VALUES (1, 1, 'a', 0.9, 'ocr', 'en'), (1, 2, 'b', 0.5, 'ocr', 'te'),
                       (1, 3, 'c', 0.7, 'ocr', 'te');
            """
        )

        assert Metrics.document_language(storage, 1, "pdf") == "te"


class TestMigration:
    def test_existing_statistics_become_english_and_keep_their_values(self, tmp_path):
        path = tmp_path / "vethuq.db"
        conn = Db.connect(path)
        conn.execute("DROP TABLE processing_metrics")
        conn.execute("DROP TABLE confidence_metrics")
        conn.execute(
            "CREATE TABLE processing_metrics (phase INTEGER NOT NULL DEFAULT 1, "
            "file_type TEXT NOT NULL, extension TEXT NOT NULL, size_bucket TEXT NOT NULL, "
            "document_count INTEGER NOT NULL DEFAULT 0, "
            "avg_duration_seconds REAL NOT NULL DEFAULT 0, "
            "avg_peak_memory_mb REAL NOT NULL DEFAULT 0, avg_cpu_percent REAL NOT NULL DEFAULT 0, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (phase, file_type, extension, size_bucket))"
        )
        conn.execute(
            "CREATE TABLE confidence_metrics (file_type TEXT NOT NULL, extension TEXT NOT NULL, "
            "process_type TEXT NOT NULL, page_count INTEGER NOT NULL DEFAULT 0, "
            "avg_confidence REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, "
            "PRIMARY KEY (file_type, extension, process_type))"
        )
        conn.execute(
            "INSERT INTO processing_metrics VALUES (2, 'image', 'png', 'small', 4, 6.5, "
            "120, 15, 'then')"
        )
        conn.execute("INSERT INTO confidence_metrics VALUES ('pdf', 'pdf', 'ocr', 7, 0.82, 'then')")
        conn.execute("UPDATE schema_version SET version = 32")
        conn.commit()
        conn.close()

        conn = Db.connect(path)
        try:
            processing = conn.execute("SELECT * FROM processing_metrics").fetchall()
            confidence = conn.execute("SELECT * FROM confidence_metrics").fetchall()
            version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
            # Both languages can now hold a row for the same key.
            conn.execute(
                "INSERT INTO processing_metrics (phase, file_type, extension, size_bucket, "
                "updated_at, language) VALUES (2, 'image', 'png', 'small', 'now', 'te')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO processing_metrics (phase, file_type, extension, size_bucket, "
                    "updated_at, language) VALUES (2, 'image', 'png', 'small', 'now', 'te')"
                )
        finally:
            conn.close()

        assert version == Db.SCHEMA_VERSION
        assert len(processing) == 1 and len(confidence) == 1
        assert processing[0]["language"] == "en"
        assert processing[0]["avg_duration_seconds"] == 6.5
        assert processing[0]["document_count"] == 4
        assert confidence[0]["language"] == "en"
        assert confidence[0]["avg_confidence"] == 0.82
