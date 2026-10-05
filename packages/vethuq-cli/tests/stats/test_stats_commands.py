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


def _seed_two_languages(db_path):
    conn = db_module.Db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO processing_metrics (file_type, extension, size_bucket, document_count, "
            "avg_duration_seconds, avg_peak_memory_mb, avg_cpu_percent, updated_at, language) "
            "VALUES ('image', 'png', 'small', 3, 2.0, 50.0, 5.0, 'x', 'en'), "
            "('image', 'png', 'small', 1, 9.0, 80.0, 8.0, 'x', 'te')"
        )
        conn.execute(
            "INSERT INTO confidence_metrics (file_type, extension, process_type, page_count, "
            "avg_confidence, updated_at, language) "
            "VALUES ('image', 'png', 'ocr', 4, 0.93, 'x', 'en'), "
            "('image', 'png', 'ocr', 2, 0.71, 'x', 'te')"
        )
        conn.commit()
    finally:
        conn.close()


class TestShowLanguages:
    def test_one_language_has_no_language_column(self, use_temp_db):
        _seed_metrics(use_temp_db())

        result = runner.invoke(app, ["stats", "show"])

        assert "Language" not in result.stdout

    def test_two_languages_are_listed_apart(self, use_temp_db):
        _seed_two_languages(use_temp_db())

        result = runner.invoke(app, ["stats", "show"])

        assert result.exit_code == 0
        assert "Language" in result.stdout
        assert "English" in result.stdout and "Telugu" in result.stdout
        assert "93%" in result.stdout and "71%" in result.stdout

    def test_lang_limits_the_statistics_to_one_language(self, use_temp_db):
        _seed_two_languages(use_temp_db())

        result = runner.invoke(app, ["stats", "show", "--lang", "te"])

        assert result.exit_code == 0
        assert "71%" in result.stdout
        assert "93%" not in result.stdout

    def test_an_unknown_language_is_a_usage_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["stats", "show", "--lang", "xx"])

        assert result.exit_code == 2
