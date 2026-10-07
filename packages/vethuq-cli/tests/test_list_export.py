"""`--export` / `--format` on the listing commands (JSON and HTML)."""

import json
from datetime import UTC, datetime

import pytest
import vethuq_core.db as db_module
from search.test_search_commands import _seed_indexed_pdf
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _html(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "{{" not in text
    return text


def _seed_runs(db_path):
    conn = db_module.Db.connect(db_path)
    for status, started in (("completed", datetime.now(UTC).isoformat()), ("failed", "2020-01-01")):
        conn.execute(
            "INSERT INTO index_runs (target, status, pid, total_files, processed_files, "
            "failed_files, started_at) VALUES (NULL, ?, 1, 3, 3, 0, ?)",
            (status, started),
        )
    conn.commit()
    conn.close()


class TestIndexHistory:
    def test_json(self, use_temp_db, tmp_path):
        _seed_runs(use_temp_db())
        out = tmp_path / "runs.json"

        result = runner.invoke(app, ["index", "history", "--export", str(out), "--format", "json"])

        assert result.exit_code == 0
        assert "Exported 2 run(s)" in result.output
        data = _json(out)
        assert data["count"] == 2
        assert {r["status"] for r in data["runs"]} == {"completed", "failed"}

    def test_html_uses_the_branded_template(self, use_temp_db, tmp_path):
        _seed_runs(use_temp_db())
        out = tmp_path / "runs.html"

        result = runner.invoke(app, ["index", "history", "--export", str(out), "--format", "html"])

        assert result.exit_code == 0
        text = _html(out)
        assert "Index history" in text
        assert 'class="pill ok"' in text and 'class="pill bad"' in text
        assert 'data-facet="status"' in text

    def test_format_needs_export(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "history", "--format", "json"])

        assert result.exit_code == 1
        assert "--format needs --export" in result.output

    def test_an_unknown_format_is_refused(self, use_temp_db, tmp_path):
        use_temp_db()

        result = runner.invoke(
            app, ["index", "history", "--export", str(tmp_path / "x"), "--format", "csv"]
        )

        assert result.exit_code == 1
        assert not (tmp_path / "x").exists()


class TestIndexStatus:
    @pytest.fixture
    def source(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/été-日本.pdf", "x")
        conn = db_module.Db.connect(db_path)
        conn.execute("UPDATE document_index SET source_id = (SELECT MIN(id) FROM sources)")
        conn.commit()
        conn.close()

    def test_json_keeps_unicode_names(self, source, tmp_path):
        out = tmp_path / "files.json"

        result = runner.invoke(
            app, ["index", "status", "1", "--export", str(out), "--format", "json"]
        )

        assert result.exit_code == 0
        assert "été-日本.pdf" in out.read_text(encoding="utf-8")
        assert _json(out)["files"][0]["status"] == "indexed"

    def test_html(self, source, tmp_path):
        out = tmp_path / "files.html"

        result = runner.invoke(
            app, ["index", "status", "1", "--export", str(out), "--format", "html"]
        )

        assert result.exit_code == 0
        text = _html(out)
        assert "été-日本.pdf" in text and "Index status of" in text

    def test_needs_a_source(self, use_temp_db, tmp_path):
        use_temp_db()

        result = runner.invoke(app, ["index", "status", "--export", str(tmp_path / "x.json")])

        assert result.exit_code == 1
        assert "need a source" in result.output


class TestCatalogs:
    @pytest.mark.parametrize(
        ("command", "key", "name_field"),
        [
            (["file-types", "list"], "file_types", "type"),
            (["search-engines", "list"], "search_engines", "name"),
        ],
    )
    def test_json(self, use_temp_db, tmp_path, command, key, name_field):
        use_temp_db()
        out = tmp_path / "out.json"

        result = runner.invoke(app, [*command, "--all", "--export", str(out), "--format", "json"])

        assert result.exit_code == 0
        data = _json(out)
        assert data["count"] == len(data[key]) > 0
        assert all(name_field in item and "status" in item for item in data[key])

    @pytest.mark.parametrize("command", [["file-types", "list"], ["search-engines", "list"]])
    def test_html(self, use_temp_db, tmp_path, command):
        use_temp_db()
        out = tmp_path / "out.html"

        result = runner.invoke(app, [*command, "--export", str(out), "--format", "html"])

        assert result.exit_code == 0
        assert "<table" in _html(out)

    def test_the_default_format_is_used(self, use_temp_db, tmp_path):
        use_temp_db()
        out = tmp_path / "out"

        result = runner.invoke(app, ["file-types", "list", "--export", str(out)])

        assert result.exit_code == 0
        assert "(json)" in result.output or "(html)" in result.output


class TestOcrModels:
    def test_json(self, use_temp_db, tmp_path):
        use_temp_db()
        out = tmp_path / "models.json"

        result = runner.invoke(
            app, ["ocr", "models", "status", "--export", str(out), "--format", "json"]
        )

        assert result.exit_code == 0
        assert _json(out)["count"] == len(_json(out)["models"])

    def test_html(self, use_temp_db, tmp_path):
        use_temp_db()
        out = tmp_path / "models.html"

        result = runner.invoke(
            app, ["ocr", "models", "status", "--export", str(out), "--format", "html"]
        )

        assert result.exit_code == 0
        assert "OCR models" in _html(out)


class TestBackups:
    def test_json_and_html(self, use_temp_db, tmp_path):
        use_temp_db()
        created = runner.invoke(app, ["db", "backup", "create"])
        assert created.exit_code == 0
        as_json, as_html = tmp_path / "b.json", tmp_path / "b.html"

        first = runner.invoke(
            app, ["db", "backup", "list", "--export", str(as_json), "--format", "json"]
        )
        second = runner.invoke(
            app, ["db", "backup", "list", "--export", str(as_html), "--format", "html"]
        )

        assert first.exit_code == 0 and second.exit_code == 0
        assert _json(as_json)["count"] >= 1
        assert "Database backups" in _html(as_html)
