from vethuq_core.db import Db


class TestSchema:
    def test_connect_creates_processing_metrics_table(self, tmp_path):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
            assert columns == {
                "phase",
                "file_type",
                "extension",
                "size_bucket",
                "document_count",
                "avg_duration_seconds",
                "avg_peak_memory_mb",
                "avg_cpu_percent",
                "updated_at",
                "language",
            }
        finally:
            conn.close()

    def test_connect_creates_confidence_metrics_table(self, tmp_path):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(confidence_metrics)")}
            assert columns == {
                "file_type",
                "extension",
                "process_type",
                "page_count",
                "avg_confidence",
                "updated_at",
                "language",
            }
        finally:
            conn.close()
