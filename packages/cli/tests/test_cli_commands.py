from __future__ import annotations

from vethuq_cli.state import State


def test_help_lists_the_groups(run):
    result = run("--help")
    assert result.exit_code == 0
    for word in ("source", "index", "search", "settings", "languages", "file-types", "db"):
        assert word in result.output


def test_no_subcommand_shows_help_not_an_interactive_console(run):
    result = run()
    assert "Usage" in result.output


def test_version(run):
    assert run("version").exit_code == 0


class TestSourcesAndIndex:
    def test_add_index_and_search(self, run, docs):
        assert "Added source 1" in run("source", "add", str(docs)).output
        out = run("index", "run").output
        assert "completed" in out and "files processed" in out
        found = run("search", "museum", "--engine", "like").output
        assert "1 match" in found and "a.txt" in found and "hello museum world" in found

    def test_source_list_and_files_and_json(self, run, run_json, docs):
        run("source", "add", str(docs))
        run("index", "run")
        assert run_json("source", "list")[0]["path"] == str(docs)
        names = {f["name"] for f in run_json("source", "files", "1")}
        assert names == {"a.txt", "b.txt"}

    def test_an_empty_list_says_how_to_add(self, run):
        assert "vethuq source add" in run("source", "list").output

    def test_remove_and_purge(self, run, docs):
        run("source", "add", str(docs))
        assert "Removed source 1" in run("source", "remove", "1").output
        assert "Purged source 1" in run("source", "purge", "1").output

    def test_index_status_history_and_clear_stale(self, run, run_json, docs):
        assert "No index run yet" in run("index", "status").output
        run("source", "add", str(docs))
        run("index", "run")
        status = run_json("index", "status")
        assert status["finished"] is True and status["stalled"] is False
        assert run_json("index", "history")[0]["status"] == "completed"
        assert "Cleared 0" in run("index", "clear-stale").output

    def test_reindex_a_file(self, run, docs):
        run("source", "add", str(docs))
        run("index", "run")
        assert "completed" in run("index", "reindex", "file", str(docs / "a.txt")).output

    def test_control_without_a_run_is_a_clean_error(self, run):
        result = run("index", "pause")
        assert result.exit_code != 0


class TestSearch:
    def test_options_and_normalizers_reach_the_engine(self, run, docs):
        run("source", "add", str(docs))
        run("index", "run")
        out = run("search", "MUSEUM", "-e", "like", "-n", "case=ignore").output
        assert "1 match" in out
        out = run("search", "museum", "-e", "fuzzy", "-o", "fuzzy.threshold=loose").output
        assert "match" in out

    def test_a_bad_option_is_an_error(self, run, docs):
        run("source", "add", str(docs))
        run("index", "run")
        assert run("search", "museum", "-e", "like", "-o", "like.nope=1").exit_code != 0

    def test_engines_and_normalizers(self, run, run_json):
        assert {"like", "exact"} <= {e["id"] for e in run_json("search-engines", "list")}
        assert "case" in {n["id"] for n in run_json("search-engines", "normalizers")}

    def test_rebuild_and_status(self, run, docs):
        run("source", "add", str(docs))
        run("index", "run")
        assert "Rebuilt: 2 pages" in run("search-index", "rebuild").output
        assert run("search-index", "status").exit_code == 0


class TestOthers:
    def test_file_types_and_languages_and_addons(self, run, run_json):
        assert "txt" in {t["id"] for t in run_json("file-types", "list")}
        assert run_json("languages", "list")[0]["id"] == "en"
        assert "english" in {a["id"] for a in run_json("addons", "list")}

    def test_stats_credits_tiers_metrics(self, run, docs):
        run("source", "add", str(docs))
        run("index", "run")
        for args in (
            ("stats", "show"),
            ("stats", "failures"),
            ("credits", "balance"),
            ("credits", "history"),
            ("tiers", "list"),
            ("metrics", "status"),
            ("updates", "status"),
            ("policy", "show"),
            ("ocr", "models", "list"),
            ("logs", "--list"),
        ):
            assert run(*args).exit_code == 0, args

    def test_db_integrity_check(self, run):
        assert "ok" in run("db", "integrity-check").output.lower()

    def test_a_vethuq_error_is_reported_cleanly(self, run):
        result = run("source", "remove", "99")
        assert result.exit_code != 0


class TestQueueAndService:
    def test_submit_list_show_cancel(self, run, run_json, docs):
        run("source", "add", str(docs))
        assert "Queued request 1" in run("index", "submit").output
        assert run_json("index", "queue", "list")[0]["status"] == "queued"
        assert run_json("index", "queue", "show", "1")["mode"] == "run"
        assert "Cancelled request 1" in run("index", "queue", "cancel", "1").output
        assert run_json("index", "queue", "list", "--status", "cancelled")[0]["id"] == 1

    def test_an_unknown_request_is_a_clean_error(self, run):
        assert run("index", "queue", "show", "9").exit_code != 0

    def test_with_a_service_running_index_run_queues_its_work(self, run, run_json, docs):
        run("source", "add", str(docs))
        State.client().index.queue.announce_service()
        out = run("index", "run").output
        assert "Queued request 1 for the background service" in out
        assert run_json("index", "history") == []
        assert run_json("index", "queue", "list")[0]["mode"] == "run"

    def test_one_off_runs_here_even_with_a_service(self, run, run_json, docs):
        run("source", "add", str(docs))
        State.client().index.queue.announce_service()
        assert "completed" in run("index", "run", "--one-off").output
        assert run_json("index", "queue", "list") == []

    def test_without_a_service_nothing_is_queued(self, run, docs):
        run("source", "add", str(docs))
        assert "completed" in run("index", "run").output


def test_source_list_and_files_sort(run, run_json, docs):
    run("source", "add", str(docs))
    assert run("source", "list", "--sort-by", "path", "--order", "desc").exit_code == 0
    asc = [f["name"] for f in run_json("source", "files", "1", "--sort-by", "name")]
    desc = [f["name"] for f in run_json("source", "files", "1", "--order", "desc")]
    assert desc == sorted(asc, reverse=True)
    assert run("source", "files", "1", "--sort-by", "bogus").exit_code != 0
