from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.db import Db
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import open_storage

runner = CliRunner()


class TestInteractiveMenu:
    def test_no_args_shows_banner_and_main_menu(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="8\n")

        assert result.exit_code == 0
        assert "VethuQ" in result.stdout
        assert "Main Menu" in result.stdout
        assert "Goodbye." in result.stdout

    def test_sources_list_then_back_then_exit(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="2\n1\n0\n8\n")

        assert result.exit_code == 0
        assert "No sources registered yet." in result.stdout

    def test_settings_gpu_status_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n1\n3\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "GPU: " in result.stdout

    def test_db_integrity_check_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="6\n1\n0\n8\n")

        assert result.exit_code == 0
        assert "passed" in result.stdout

    def test_settings_db_integrity_check_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n5\n1\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Integrity check: " in result.stdout

    def test_settings_logs_level_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n6\n1\n2\ndebug\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Log level set to debug." in result.stdout
        assert "Log level: debug" in result.stdout

    def test_settings_logs_retention_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n6\n2\n2\n30\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Log retention set to 30 days." in result.stdout
        assert "Log retention: 30 days" in result.stdout

    def test_logs_menu_shows_a_component_log(self, use_temp_db):
        db_path = use_temp_db()
        log_dir = db_path.parent / "logs"
        log_dir.mkdir()
        (log_dir / "index.log").write_text(
            "2026-10-01 10:00:00,000 INFO [MainThread] vethuq.index: hello menu\n",
            encoding="utf-8",
        )

        result = runner.invoke(app, [], input="7\n2\n10\n0\n8\n")

        assert result.exit_code == 0
        assert "hello menu" in result.stdout

    def test_invalid_selection_then_quit(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="9\nq\n")

        assert result.exit_code == 0
        assert "Invalid selection." in result.stdout
        assert "Goodbye." in result.stdout

    def test_existing_subcommand_still_works_directly(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["source", "list"])

        assert result.exit_code == 0
        assert "Main Menu" not in result.stdout

    def test_settings_index_stability_check_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n3\n4\n2\n0.5\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Stability check set to 0.5 seconds." in result.stdout
        assert "Stability check: 0.5 seconds" in result.stdout

    def test_settings_ocr_retry_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n4\n1\n2\n5\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "OCR retry attempts set to 5." in result.stdout
        assert "OCR retry attempts: 5" in result.stdout

    def test_settings_ocr_engine_set_and_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n4\n2\n2\ndeep\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "deep" in result.stdout


def _seed_page(db_path, text: str) -> None:
    conn = Db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) "
            "VALUES ('/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute("INSERT INTO documents (created_at) VALUES ('2026-01-01T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (1, 1, '/docs/museum.pdf', 'pdf', 'indexed')"
        )
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (1, 1, ?, 0.9)",
            (text,),
        )
        conn.commit()
    finally:
        conn.close()


class TestInteractiveSearchEngines:
    def test_search_asks_for_engine_and_case_sensitivity_for_like(self, use_temp_db):
        _seed_page(use_temp_db(), "Visit the Museum today")

        # Search > text > engine (like) > case-sensitive? no, then exit.
        result = runner.invoke(app, [], input="1\nmuseum\nlike\nn\n8\n")

        assert result.exit_code == 0
        assert "Results: 1 match (engine: like)" in result.stdout

    def test_case_sensitive_answer_is_applied_for_like(self, use_temp_db):
        _seed_page(use_temp_db(), "Visit the Museum today")

        result = runner.invoke(app, [], input="1\nmuseum\nlike\ny\n8\n")

        assert "No matches found." in result.stdout

    def test_skips_case_question_for_other_engines(self, use_temp_db):
        _seed_page(use_temp_db(), "Visit the Museum today")

        # No case-sensitive answer is given: prompting for one would eat the "8" and hang.
        result = runner.invoke(app, [], input="1\nMuseum\nexact\n8\n")

        assert result.exit_code == 0
        assert "Results: 1 match (engine: exact, case-sensitive)" in result.stdout
        assert "Case-sensitive?" not in result.stdout

    def test_prompts_default_to_the_stored_engine(self, use_temp_db):
        db_path = use_temp_db()
        _seed_page(db_path, "Visit the Museum today")
        storage = open_storage(db_path)
        try:
            SearchSettings.set_engine(storage, "full-text")
        finally:
            storage.close()

        # Enter accepts the default engine (full-text), which asks nothing further.
        result = runner.invoke(app, [], input="1\nmuseums\n\n8\n")

        assert "Results: 1 match (engine: full-text)" in result.stdout

    def test_settings_search_engine_and_case_sensitive_navigation(self, use_temp_db):
        use_temp_db()

        # Settings > Search > Engine > Set exact; Show; back. Case Sensitive > Enable; Show; back.
        result = runner.invoke(app, [], input="4\n2\n3\n2\nexact\n1\n0\n4\n2\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Search engine set to exact." in result.stdout
        assert "Search engine: exact" in result.stdout
        assert "Search will match case by default." in result.stdout
