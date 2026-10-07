"""`--sort` and `--sort-by` on the listing commands."""

import json
from datetime import UTC, datetime

import pytest
import vethuq_core.db as db_module
from search.test_search_commands import _flatten, _seed_indexed_pdf
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.index import IndexJobs, IndexRunner
from vethuq_core.search.engines.catalog import SearchEngineCatalog

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: True))


def _files_in_output(output: str, names: list[str]) -> list[str]:
    flat = _flatten(output)
    return sorted((n for n in names if n in flat), key=flat.index)


class TestSearch:
    NAMES = ["a.pdf", "b.pdf", "c.pdf"]

    @pytest.fixture
    def seeded(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/b.pdf", "museum museum museum")
        _seed_indexed_pdf(db_path, "/docs/c.pdf", "museum")
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "museum museum")
        return db_path

    @pytest.mark.parametrize("engine", ["like", "all"])
    def test_sort_by_file_ascending(self, seeded, engine):
        result = runner.invoke(
            app, ["search", "museum", "--engine", engine, "--sort-by", "file", "--sort", "asc"]
        )

        assert result.exit_code == 0
        assert _files_in_output(result.output, self.NAMES) == ["a.pdf", "b.pdf", "c.pdf"]

    @pytest.mark.parametrize("engine", ["like", "all"])
    def test_sort_descending_alone_sorts_by_file(self, seeded, engine):
        result = runner.invoke(app, ["search", "museum", "--engine", engine, "--sort", "desc"])

        assert result.exit_code == 0
        assert _files_in_output(result.output, self.NAMES) == ["c.pdf", "b.pdf", "a.pdf"]

    def test_the_underscore_spelling_works(self, seeded):
        result = runner.invoke(
            app, ["search", "museum", "--engine", "like", "--sort_by", "file", "--sort", "desc"]
        )

        assert result.exit_code == 0
        assert _files_in_output(result.output, self.NAMES) == ["c.pdf", "b.pdf", "a.pdf"]

    def test_the_export_follows_the_sort(self, seeded, tmp_path):
        output = tmp_path / "out.json"

        result = runner.invoke(
            app,
            [
                "search",
                "museum",
                "--engine",
                "like",
                "--sort",
                "desc",
                "--export",
                str(output),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        names = [m["file_name"] for m in json.loads(output.read_text(encoding="utf-8"))["matches"]]
        assert names[0] == "c.pdf" and names[-1] == "a.pdf"
        assert names == sorted(names, reverse=True)

    def test_an_unknown_column_is_rejected(self, seeded):
        result = runner.invoke(app, ["search", "museum", "--sort-by", "colour"])

        assert result.exit_code == 2

    def test_unicode_file_names_sort(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/été.pdf", "contenu")
        _seed_indexed_pdf(db_path, "/docs/abc.pdf", "contenu")

        result = runner.invoke(app, ["search", "contenu", "--engine", "like", "--sort", "asc"])

        assert _files_in_output(result.output, ["abc.pdf", "été.pdf"]) == ["abc.pdf", "été.pdf"]


class TestQueue:
    def _enqueue(self):
        first = IndexJobs.enqueue("1")
        second = IndexJobs.enqueue(None, restart=True)
        return first, second

    def test_default_is_oldest_first(self, use_temp_db):
        use_temp_db()
        first, second = self._enqueue()

        result = runner.invoke(app, ["index", "queue", "list", "--json"])

        assert [j["id"] for j in json.loads(result.output)] == [first.id, second.id]

    def test_sort_descending(self, use_temp_db):
        use_temp_db()
        first, second = self._enqueue()

        result = runner.invoke(app, ["index", "queue", "list", "--json", "--sort", "desc"])

        assert [j["id"] for j in json.loads(result.output)] == [second.id, first.id]

    def test_sort_by_kind(self, use_temp_db):
        use_temp_db()
        first, second = self._enqueue()

        result = runner.invoke(
            app, ["index", "queue", "list", "--json", "--sort-by", "kind", "--sort", "desc"]
        )

        assert [j["mode"] for j in json.loads(result.output)] == ["run", "restart"]
        assert [j["id"] for j in json.loads(result.output)] == [first.id, second.id]

    def test_the_table_is_sorted_too(self, use_temp_db):
        use_temp_db()
        IndexJobs.enqueue("alpha")
        IndexJobs.enqueue("omega")

        result = runner.invoke(
            app, ["index", "queue", "list", "--sort-by", "target", "--sort", "desc"]
        )

        output = _flatten(result.output)
        assert output.index("omega") < output.index("alpha")


class TestHistory:
    def _runs(self, db_path):
        conn = db_module.Db.connect(db_path)
        now = datetime.now(UTC).isoformat()
        for status, started in (("completed", now), ("failed", "2020-01-01T00:00:00+00:00")):
            conn.execute(
                "INSERT INTO index_runs (target, status, pid, total_files, processed_files, "
                "failed_files, started_at) VALUES (NULL, ?, 1, 3, 3, 0, ?)",
                (status, started),
            )
        conn.commit()
        conn.close()

    def test_sort_by_started_ascending(self, use_temp_db):
        self._runs(use_temp_db())

        result = runner.invoke(app, ["index", "history", "--json", "--sort-by", "started"])

        assert [r["status"] for r in json.loads(result.output)] == ["failed", "completed"]

    def test_sort_by_status_descending(self, use_temp_db):
        self._runs(use_temp_db())

        result = runner.invoke(
            app, ["index", "history", "--json", "--sort-by", "status", "--sort", "desc"]
        )

        assert [r["status"] for r in json.loads(result.output)] == ["failed", "completed"]


class TestIndexStatus:
    def test_sort_files_by_name(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/b.pdf", "x")
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "x")
        conn = db_module.Db.connect(db_path)
        conn.execute("UPDATE document_index SET source_id = (SELECT MIN(id) FROM sources)")
        conn.commit()
        conn.close()

        ascending = runner.invoke(app, ["index", "status", "1", "--json", "--sort", "asc"])
        descending = runner.invoke(app, ["index", "status", "1", "--json", "--sort", "desc"])

        assert [r["file"] for r in json.loads(ascending.output)] == ["/docs/a.pdf", "/docs/b.pdf"]
        assert [r["file"] for r in json.loads(descending.output)] == ["/docs/b.pdf", "/docs/a.pdf"]


class TestCatalogs:
    def test_file_types_by_name(self, use_temp_db):
        use_temp_db()

        ascending = runner.invoke(app, ["file-types", "list", "--sort-by", "name"])
        descending = runner.invoke(
            app, ["file-types", "list", "--sort-by", "name", "--sort", "desc"]
        )

        assert ascending.exit_code == 0 and descending.exit_code == 0
        assert ascending.output.index("PDF") < ascending.output.index("PNG")
        assert descending.output.index("PNG") < descending.output.index("PDF")

    def test_search_engines_by_name(self, use_temp_db):
        use_temp_db()
        labels = sorted(e.label for e in SearchEngineCatalog.installed())

        ascending = _flatten(
            runner.invoke(app, ["search-engines", "list", "--sort-by", "name"]).output
        )
        descending = _flatten(
            runner.invoke(app, ["search-engines", "list", "--sort", "desc"]).output
        )

        assert ascending.index(labels[0]) < ascending.index(labels[-1])
        assert descending.index(labels[-1]) < descending.index(labels[0])
