import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _seed_metrics(db_path):
    conn = db_module.Db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO processing_metrics "
            "(file_type, extension, size_bucket, document_count, avg_duration_seconds, "
            "avg_peak_memory_mb, avg_cpu_percent, updated_at) "
            "VALUES ('pdf', 'pdf', 'medium', 2, 5.0, 100.0, 10.0, '2026-01-01T00:00:00+00:00'), "
            "('image', 'png', 'small', 1, 1.0, 50.0, 5.0, '2026-01-01T00:00:00+00:00'), "
            "('image', 'jpg', 'small', 4, 2.0, 60.0, 6.0, '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO confidence_metrics "
            "(file_type, extension, process_type, page_count, avg_confidence, updated_at) "
            "VALUES ('pdf', 'pdf', 'native', 3, 1.0, '2026-01-01T00:00:00+00:00'), "
            "('image', 'png', 'ocr', 2, 0.8, '2026-01-01T00:00:00+00:00'), "
            "('image', 'jpg', 'ocr', 5, 0.6, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()


class TestShow:
    def test_show_with_no_statistics(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["stats", "show"])

        assert result.exit_code == 0
        assert "No processing statistics recorded yet." in result.stdout
        assert "No confidence statistics recorded yet." in result.stdout

    def test_show_displays_seeded_statistics(self, use_temp_db):
        db_path = use_temp_db()
        _seed_metrics(db_path)

        result = runner.invoke(app, ["stats", "show"])

        assert result.exit_code == 0
        assert "pdf" in result.stdout
        assert "native" in result.stdout
        assert "100%" in result.stdout

    def test_show_lists_png_and_jpg_separately(self, use_temp_db):
        db_path = use_temp_db()
        _seed_metrics(db_path)

        result = runner.invoke(app, ["stats", "show"], terminal_width=120)

        assert "Extension" in result.stdout
        assert "png" in result.stdout
        assert "jpg" in result.stdout
        assert "80%" in result.stdout
        assert "60%" in result.stdout
        assert "image" not in result.stdout


class TestReset:
    def test_reset_declined_leaves_statistics_intact(self, use_temp_db):
        db_path = use_temp_db()
        _seed_metrics(db_path)

        result = runner.invoke(app, ["stats", "reset"], input="n\n")

        assert result.exit_code == 0
        assert "Statistics reset." not in result.stdout

        conn = db_module.Db.connect(db_path)
        try:
            assert conn.execute("SELECT * FROM processing_metrics").fetchone() is not None
        finally:
            conn.close()

    def test_reset_confirmed_clears_statistics(self, use_temp_db):
        db_path = use_temp_db()
        _seed_metrics(db_path)

        result = runner.invoke(app, ["stats", "reset"], input="y\n")

        assert result.exit_code == 0
        assert "Statistics reset." in result.stdout

        conn = db_module.Db.connect(db_path)
        try:
            assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
            assert conn.execute("SELECT * FROM confidence_metrics").fetchone() is None
        finally:
            conn.close()

    def test_reset_force_skips_confirmation(self, use_temp_db):
        db_path = use_temp_db()
        _seed_metrics(db_path)

        result = runner.invoke(app, ["stats", "reset", "--force"])

        assert result.exit_code == 0
        assert "Statistics reset." in result.stdout

        conn = db_module.Db.connect(db_path)
        try:
            assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
        finally:
            conn.close()
