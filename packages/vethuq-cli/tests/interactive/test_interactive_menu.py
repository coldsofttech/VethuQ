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

    def test_header_panel_shows_the_app_name_and_tagline(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="8\n")

        assert "VethuQ" in result.stdout
        assert "Document intelligence and evidence infrastructure." in result.stdout

    def test_each_menu_is_a_panel_listing_its_numbered_items(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n1\n0\n0\n8\n")

        assert "Main Menu" in result.stdout
        assert "Settings > GPU" in result.stdout
        assert "Enable" in result.stdout and "Back" in result.stdout
        assert "Enter a number - q to quit" in result.stdout

    def test_an_invalid_selection_asks_again(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="9\n8\n")

        assert "Invalid selection" in result.output
        assert "Goodbye." in result.stdout

    def test_q_leaves_the_shell_from_any_menu(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\nq\n")

        assert result.exit_code == 0
        assert "Goodbye." in result.stdout

    def test_sources_list_then_back_then_exit(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="2\n1\n\n\n\n0\n8\n")

        assert result.exit_code == 0
        assert "No sources registered yet." in result.stdout

    def test_sources_list_files_with_detail(self, use_temp_db, tmp_path):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(tmp_path)])

        result = runner.invoke(app, [], input=f"2\n2\n{tmp_path}\ny\n\n\n\n0\n8\n")

        assert result.exit_code == 0
        assert "No files indexed yet for this source." in result.stdout

    def test_sources_list_files_unknown_source_keeps_shell_alive(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="2\n2\n99\nn\n\n\n\n0\n8\n")

        assert result.exit_code == 0
        assert "No active source matches" in result.output
        assert "Goodbye." in result.stdout

    def test_sources_list_files_export_from_menu(self, use_temp_db, tmp_path):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(tmp_path)])
        out = tmp_path / "out.html"

        result = runner.invoke(app, [], input=f"2\n2\n{tmp_path}\nn\n\n\n{out}\nhtml\n0\n8\n")

        assert result.exit_code == 0
        assert "Exported 0 file(s)" in result.stdout
        assert out.read_text().startswith("<!doctype html>")

    def test_index_reindex_source_unknown_source_keeps_shell_alive(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="3\n8\n99\nn\n\n\n0\n8\n")

        assert result.exit_code == 0
        assert "No active source matches" in result.output
        assert "Goodbye." in result.stdout

    def test_index_reindex_untracked_file_keeps_shell_alive(self, use_temp_db, tmp_path):
        use_temp_db()
        answers = ["3", "9", str(tmp_path / "x.pdf"), "", "n", "", "", "0", "8"]

        result = runner.invoke(app, [], input="\n".join(answers) + "\n")

        assert result.exit_code == 0
        assert "isn't tracked" in " ".join(result.output.split())
        assert "Goodbye." in result.stdout

    def test_index_rebuild_search_asks_for_confirmation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="3\n10\nn\n0\n8\n")

        assert result.exit_code == 0
        assert "Rebuild search index" in result.output
        assert "Aborted." in result.output
        assert "Goodbye." in result.stdout

    def test_index_rebuild_search_runs_when_confirmed(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="3\n10\ny\n0\n8\n")

        assert result.exit_code == 0
        assert "6 rebuilt, 0 failed" in " ".join(result.output.split())

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

    def test_settings_db_backup_show_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n5\n2\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Automatic backup: " in result.stdout

    def test_db_backup_create_and_list_navigation(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="6\n2\n1\nsnap\n\n2\n\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "snap" in result.stdout

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

    def test_fuzzy_asks_for_case_and_fuzziness(self, use_temp_db):
        _seed_page(use_temp_db(), "Visit the Museurn today")

        # Search > text > engine (fuzzy) > case-sensitive? no > fuzziness loose, then exit.
        result = runner.invoke(app, [], input="1\nMuseum\nfuzzy\nn\nloose\n8\n")

        assert result.exit_code == 0
        assert "Results: 1 match (engine: fuzzy, threshold 65%)" in result.stdout

    def test_fuzzy_accepts_a_number_and_defaults_to_the_stored_threshold(self, use_temp_db):
        db_path = use_temp_db()
        _seed_page(db_path, "Visit the Museurn today")

        numeric = runner.invoke(app, [], input="1\nMuseum\nfuzzy\nn\n0.7\n8\n")
        assert "threshold 70%" in numeric.stdout

        storage = open_storage(db_path)
        try:
            SearchSettings.set_fuzzy_threshold(storage, "loose")
        finally:
            storage.close()
        # Enter accepts the stored default (loose).
        default = runner.invoke(app, [], input="1\nMuseum\nfuzzy\nn\n\n8\n")
        assert "threshold 65%" in default.stdout

    def test_fuzzy_rejects_an_invalid_fuzziness_answer(self, use_temp_db):
        _seed_page(use_temp_db(), "Visit the Museum today")

        result = runner.invoke(app, [], input="1\nMuseum\nfuzzy\nn\nsloppy\n8\n")

        assert result.exit_code == 0
        assert "Results:" not in result.output
        assert "threshold must be" in result.output

    def test_settings_fuzzy_threshold_navigation(self, use_temp_db):
        use_temp_db()

        # Settings > Search > Fuzzy Threshold > Set loose; Show; back out.
        result = runner.invoke(app, [], input="4\n2\n5\n2\nloose\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Search fuzzy threshold set to loose." in result.stdout
        assert "Search fuzzy threshold: loose" in result.stdout

    def test_settings_normalize_leetspeak_navigation(self, use_temp_db):
        use_temp_db()

        # Settings > Search > Normalize > Leetspeak > Set extended; Show; back out.
        result = runner.invoke(app, [], input="4\n2\n7\n2\n2\nextended\n1\n0\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Search leetspeak set to extended." in result.stdout
        assert "Search leetspeak: extended" in result.stdout

    def test_settings_normalize_case_navigation(self, use_temp_db):
        use_temp_db()

        # Settings > Search > Normalize > Case > Set match; Show; back out.
        result = runner.invoke(app, [], input="4\n2\n7\n1\n2\nmatch\n1\n0\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Search case set to match." in result.stdout
        assert "Search case: match" in result.stdout

    def test_settings_normalize_rejects_an_unknown_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, [], input="4\n2\n7\n2\n2\ninsane\n0\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "off, basic, standard, extended" in result.output

    def test_noise_fuzzy_accepts_off_as_the_leet_level(self, use_temp_db):
        _seed_page(use_temp_db(), "say h3ll0 to all")

        # Search > text > engine > case-sensitive? no > fuzziness > leet level off > noise, exit.
        result = runner.invoke(app, [], input="1\nhello\nnoise-fuzzy\nn\n\noff\n\n8\n")

        assert result.exit_code == 0
        assert "No matches found." in result.stdout

    def test_like_does_not_ask_about_look_alikes(self, use_temp_db):
        db_path = use_temp_db()
        _seed_page(db_path, "say h3ll0 to all")
        storage = open_storage(db_path)
        try:
            SearchSettings.set_leetspeak(storage, "basic")
        finally:
            storage.close()

        result = runner.invoke(app, [], input="1\nhello\nlike\nn\n8\n")

        assert "Leet level" not in result.stdout
        assert "h3ll0" in result.stdout  # the stored setting applied

    def test_settings_noise_level_navigation(self, use_temp_db):
        use_temp_db()

        # Settings > Search > Noise Level > Set high; Show; back out.
        result = runner.invoke(app, [], input="4\n2\n8\n2\nhigh\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Search noise level set to high." in result.stdout
        assert "Search noise level: high" in result.stdout

    def test_noise_fuzzy_asks_for_case_fuzziness_level_and_noise(self, use_temp_db):
        _seed_page(use_temp_db(), "say h..e llo to all")

        # Search > text > engine > case-sensitive? no > fuzziness > leet level > noise, then exit.
        result = runner.invoke(
            app, [], input="1\nhello\nnoise-fuzzy\nn\nloose\nstandard\nmedium\n8\n"
        )

        assert result.exit_code == 0
        # (the panel title is cut off at 80 columns, so only its start is checked)
        assert "Results: 1 match (engine: noise-fuzzy, threshold 65%" in result.stdout
        assert "h..e llo" in result.stdout  # found, so the medium noise level was used
        for prompt in ("Case-sensitive?", "Fuzziness", "Leet level", "Noise (low, medium, high)"):
            assert prompt in result.stdout

    def test_noise_fuzzy_defaults_to_the_stored_answers_and_rejects_nonsense(self, use_temp_db):
        db_path = use_temp_db()
        _seed_page(db_path, "say h..e llo to all")
        storage = open_storage(db_path)
        try:
            SearchSettings.set_noise_level(storage, "medium")
        finally:
            storage.close()

        stored = runner.invoke(app, [], input="1\nhello\nnoise-fuzzy\nn\n\n\n\n8\n")
        bad = runner.invoke(app, [], input="1\nhello\nnoise-fuzzy\nn\n\n\nloud\n8\n")

        assert "h..e llo" in stored.stdout  # the stored medium noise level applied
        assert "Results:" not in bad.output
        assert "noise must be one of" in bad.output

    _CONTRACT = "The payment is due within thirty days, subject to the termination clause."

    def test_proximity_asks_for_a_distance_and_no_case_question(self, use_temp_db):
        _seed_page(use_temp_db(), self._CONTRACT)

        # Search > text > engine (proximity) > distance 12, then exit. No case question.
        result = runner.invoke(app, [], input="1\npayment termination\nproximity\n12\n8\n")

        assert result.exit_code == 0
        assert "Results: 1 match (engine: proximity, within 12 words)" in result.stdout
        assert "Case-sensitive?" not in result.stdout

    def test_proximity_accepts_presets_and_defaults_to_the_stored_distance(self, use_temp_db):
        db_path = use_temp_db()
        _seed_page(db_path, self._CONTRACT)

        preset = runner.invoke(app, [], input="1\npayment termination\nproximity\nloose\n8\n")
        assert "within 30 words" in preset.stdout

        storage = open_storage(db_path)
        try:
            SearchSettings.set_proximity_distance(storage, "15")
        finally:
            storage.close()
        # Enter accepts the stored default (15).
        default = runner.invoke(app, [], input="1\npayment termination\nproximity\n\n8\n")
        assert "within 15 words" in default.stdout

    def test_proximity_rejects_an_invalid_distance_answer(self, use_temp_db):
        _seed_page(use_temp_db(), self._CONTRACT)

        result = runner.invoke(app, [], input="1\npayment termination\nproximity\n0\n8\n")

        assert result.exit_code == 0
        assert "Results:" not in result.output
        assert "from 1 to 100" in result.output

    def test_settings_proximity_distance_navigation(self, use_temp_db):
        use_temp_db()

        # Settings > Search > Proximity Distance > Set tight; Show; back out.
        result = runner.invoke(app, [], input="4\n2\n6\n2\ntight\n1\n0\n0\n0\n8\n")

        assert result.exit_code == 0
        assert "Search proximity distance set to tight." in result.stdout
        assert "Search proximity distance: tight (3 words)" in result.stdout

    def test_search_defaults_to_all_engines_and_asks_about_case(self, use_temp_db):
        _seed_page(use_temp_db(), "Visit the Museum today")

        # Search > text > Enter accepts the default engine (all) > case-sensitive? no.
        result = runner.invoke(app, [], input="1\nMuseum\n\nn\n8\n")

        assert result.exit_code == 0
        assert "Results: 1 page (engine: all)" in result.stdout
        assert "[Exact]" in result.stdout
