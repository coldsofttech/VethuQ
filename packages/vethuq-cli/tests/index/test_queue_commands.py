import json

import pytest
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.index import IndexJobs, IndexRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: True))


class TestQueue:
    def _jobs(self):
        first = IndexJobs.enqueue("1")
        IndexJobs.claim_next()
        second = IndexJobs.enqueue(None, restart=True, languages="en")
        done = IndexJobs.enqueue("9")
        IndexJobs.cancel_queued()
        IndexJobs.finish(first.id, "failed", "boom")
        return first, second, done

    def test_list_shows_pending_jobs_only(self, use_temp_db):
        use_temp_db()
        IndexJobs.enqueue("1")
        IndexJobs.claim_next()
        IndexJobs.enqueue("2")
        finished = IndexJobs.enqueue("3")
        IndexJobs.claim_next()  # job 2 runs after 1 is done; simulate by finishing 1 and 2
        IndexJobs.finish(1, "completed")
        IndexJobs.finish(2, "completed")

        result = runner.invoke(app, ["index", "queue", "list", "--json"])

        assert [j["id"] for j in json.loads(result.output)] == [finished.id]

    def test_list_all_includes_finished_jobs(self, use_temp_db):
        use_temp_db()
        first, second, done = self._jobs()

        result = runner.invoke(app, ["index", "queue", "list", "--all", "--json"])

        assert {j["id"] for j in json.loads(result.output)} == {first.id, second.id, done.id}

    def test_an_empty_queue_says_so(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "queue", "list"])

        assert result.exit_code == 0
        assert "The queue is empty" in result.output

    def test_list_table(self, use_temp_db):
        use_temp_db()
        IndexJobs.enqueue(None, restart=True, languages="en")

        result = runner.invoke(app, ["index", "queue", "list"])

        assert "all sources" in result.output and "restart" in result.output
        assert "queued" in result.output

    def test_show_describes_one_job(self, use_temp_db):
        use_temp_db()
        first, _, _ = self._jobs()

        result = runner.invoke(app, ["index", "queue", "show", str(first.id)])

        assert result.exit_code == 0
        assert "failed" in result.output and "boom" in result.output
        assert "Target: 1" in result.output

    def test_show_json(self, use_temp_db):
        use_temp_db()
        job = IndexJobs.enqueue("4", languages="te")

        result = runner.invoke(app, ["index", "queue", "show", str(job.id), "--json"])

        data = json.loads(result.output)
        assert (data["target"], data["languages"], data["status"]) == ("4", "te", "queued")

    def test_show_an_unknown_job_is_an_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "queue", "show", "99"])

        assert result.exit_code == 1
        assert "No queued job has id 99" in result.output


class TestQueueExport:
    def _jobs(self):
        first = IndexJobs.enqueue("1")
        IndexJobs.claim_next()
        second = IndexJobs.enqueue(None, restart=True, languages="en")
        IndexJobs.finish(first.id, "failed", "boom")
        return first, second

    def test_json(self, use_temp_db, tmp_path):
        use_temp_db()
        first, second = self._jobs()
        out = tmp_path / "q.json"

        result = runner.invoke(
            app, ["index", "queue", "list", "--all", "--export", str(out), "--format", "json"]
        )

        assert result.exit_code == 0
        assert "Exported 2 job(s)" in result.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["count"] == 2
        assert {j["id"] for j in data["jobs"]} == {first.id, second.id}
        assert {j["target"] for j in data["jobs"]} == {"1", "all sources"}

    def test_html_shows_status_pills_and_filters(self, use_temp_db, tmp_path):
        use_temp_db()
        self._jobs()
        out = tmp_path / "q.html"

        result = runner.invoke(
            app, ["index", "queue", "list", "--all", "--export", str(out), "--format", "html"]
        )

        assert result.exit_code == 0
        text = out.read_text(encoding="utf-8")
        assert "Index queue" in text and "boom" in text
        assert 'class="pill bad"' in text and 'class="pill warn"' in text
        assert 'data-facet="status"' in text

    def test_an_empty_queue_still_exports(self, use_temp_db, tmp_path):
        use_temp_db()
        out = tmp_path / "q.json"

        result = runner.invoke(
            app, ["index", "queue", "list", "--export", str(out), "--format", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(out.read_text(encoding="utf-8"))["jobs"] == []

    def test_format_needs_export(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "queue", "list", "--format", "json"])

        assert result.exit_code == 1
