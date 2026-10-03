import json
from datetime import UTC, datetime

from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.db import Db
from vethuq_core.sources import Sources
from vethuq_core.storage.sqlite import SqliteStorage

runner = CliRunner()


def _unwrapped(output: str) -> str:
    """`output` with the panel borders and the line breaks a long path wraps at removed."""
    return "".join(output.replace("\u2502", " ").split())


class TestSource:
    def test_add_and_list_source(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()

        add_result = runner.invoke(app, ["source", "add", str(folder)])
        assert add_result.exit_code == 0
        assert "Added folder" in add_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert list_result.exit_code == 0
        assert _unwrapped(str(folder.resolve())) in _unwrapped(list_result.stdout)

    def test_add_missing_path_fails(self, use_temp_db, tmp_path):
        use_temp_db()

        result = runner.invoke(app, ["source", "add", str(tmp_path / "missing")])

        assert result.exit_code == 1

    def test_remove_source_with_force_skips_confirmation(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        remove_result = runner.invoke(app, ["source", "remove", str(folder), "--force"])
        assert remove_result.exit_code == 0
        assert "Removed folder" in remove_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert "No sources registered yet." in list_result.stdout

    def test_remove_source_confirms_before_removing(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        remove_result = runner.invoke(app, ["source", "remove", str(folder)], input="y\n")
        assert remove_result.exit_code == 0
        assert "Removed folder" in remove_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert "No sources registered yet." in list_result.stdout

    def test_remove_source_declined_leaves_source_registered(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        remove_result = runner.invoke(app, ["source", "remove", str(folder)], input="n\n")
        assert remove_result.exit_code == 0
        assert "Removed folder" not in remove_result.stdout

        list_result = runner.invoke(app, ["source", "list"])
        assert _unwrapped(str(folder.resolve())) in _unwrapped(list_result.stdout)


def _seed_files(db_path, folder):
    conn = Db.connect(db_path)
    try:
        source = Sources.add(SqliteStorage(conn), folder)
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
        ).lastrowid
        indexed_id = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status, "
            "file_size_bytes, started_at, completed_at, indexed_at) "
            "VALUES (?, ?, ?, 'pdf', 'indexed', 1536, '2026-01-01T10:00:00+00:00', "
            "'2026-01-01T10:00:03+00:00', '2026-01-01T10:00:03+00:00')",
            (source.id, document_id, str(folder / "sub" / "report.pdf")),
        ).lastrowid
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (?, 1, 'x', 0.9)",
            (indexed_id,),
        )
        failed_doc = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
        ).lastrowid
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status, "
            "error_message) VALUES (?, ?, ?, 'image', 'error', 'unreadable')",
            (source.id, failed_doc, str(folder / "scan.png")),
        )
        conn.commit()
        return source.id, indexed_id
    finally:
        conn.close()


class TestSourceListFiles:
    def test_lists_id_file_and_status(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        source_id, indexed_id = _seed_files(db_path, folder)

        result = runner.invoke(app, ["source", "list", str(source_id)])

        assert result.exit_code == 0
        assert "ID" in result.stdout and "Status" in result.stdout
        assert "sub/report.pdf" in _unwrapped(result.stdout)
        assert "scan.png" in result.stdout
        assert "indexed" in result.stdout and "error" in result.stdout
        assert str(indexed_id) in result.stdout
        assert "unreadable" not in result.stdout  # detail only
        assert "Started" not in result.stdout

    def test_accepts_a_path(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        _seed_files(db_path, folder)

        result = runner.invoke(app, ["source", "list", str(folder)])

        assert result.exit_code == 0
        assert "scan.png" in result.stdout

    def test_detail_shows_timestamps_phases_and_errors(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        source_id, _ = _seed_files(db_path, folder)

        result = runner.invoke(app, ["source", "list", str(source_id), "--detail"])

        assert result.exit_code == 0
        out = result.stdout
        for label in ("Started", "Completed", "Indexed", "OCR phase", "OCR angles", "Duration"):
            assert label in out
        assert "quick (1/1)" in out
        assert "1.5 KB" in out
        assert "3.0s" in out
        assert "90%" in out
        assert "unreadable" in out

    def test_empty_source_reports_no_files(self, use_temp_db, tmp_path):
        use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        runner.invoke(app, ["source", "add", str(folder)])

        result = runner.invoke(app, ["source", "list", str(folder)])

        assert result.exit_code == 0
        assert "No files indexed yet for this source." in result.stdout

    def test_unknown_source_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["source", "list", "42"])

        assert result.exit_code == 1

    def test_detail_without_a_source_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["source", "list", "--detail"])

        assert result.exit_code == 1


class TestSourceListExport:
    def _setup(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        source_id, indexed_id = _seed_files(db_path, folder)
        return folder, source_id, indexed_id

    def test_export_files_json(self, use_temp_db, tmp_path):
        _, source_id, indexed_id = self._setup(use_temp_db, tmp_path)
        out = tmp_path / "files.json"

        result = runner.invoke(
            app, ["source", "list", str(source_id), "--export", str(out), "--format", "json"]
        )

        assert result.exit_code == 0
        assert "Exported 2 file(s)" in result.stdout
        data = json.loads(out.read_text())
        assert data["file_count"] == 2 and data["detail"] is False
        first = next(f for f in data["files"] if f["id"] == indexed_id)
        assert set(first) == {"id", "file_name", "status"}
        assert first["file_name"] == "sub/report.pdf"

    def test_export_files_detail_json(self, use_temp_db, tmp_path):
        _, source_id, _ = self._setup(use_temp_db, tmp_path)
        out = tmp_path / "files.json"

        result = runner.invoke(
            app,
            [
                "source",
                "list",
                str(source_id),
                "--detail",
                "--export",
                str(out),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(out.read_text())
        first = next(f for f in data["files"] if f["file_name"] == "sub/report.pdf")
        assert data["detail"] is True
        assert first["size_bytes"] == 1536
        assert first["duration"] == 3.0
        assert first["ocr_phase_name"] == "quick"
        assert next(f for f in data["files"] if f["status"] == "error")["error"] == "unreadable"

    def test_export_files_html_with_and_without_detail(self, use_temp_db, tmp_path):
        _, source_id, _ = self._setup(use_temp_db, tmp_path)
        plain, detailed = tmp_path / "plain.html", tmp_path / "detail.html"

        runner.invoke(
            app, ["source", "list", str(source_id), "--export", str(plain), "--format", "html"]
        )
        runner.invoke(
            app,
            [
                "source",
                "list",
                str(source_id),
                "--detail",
                "--export",
                str(detailed),
                "--format",
                "html",
            ],
        )

        assert "<th>Status</th>" in plain.read_text()
        assert "sub/report.pdf" in plain.read_text()
        assert "<th>Completed</th>" not in plain.read_text()
        assert "<th>Completed</th>" in detailed.read_text()
        assert "unreadable" in detailed.read_text()

    def test_export_sources_json_and_html(self, use_temp_db, tmp_path):
        folder, _, _ = self._setup(use_temp_db, tmp_path)
        as_json, as_html = tmp_path / "s.json", tmp_path / "s.html"

        r1 = runner.invoke(app, ["source", "list", "--export", str(as_json), "--format", "json"])
        r2 = runner.invoke(app, ["source", "list", "--export", str(as_html), "--format", "html"])

        assert r1.exit_code == 0 and r2.exit_code == 0
        data = json.loads(as_json.read_text())
        assert data["source_count"] == 1
        assert data["sources"][0]["path"] == str(folder.resolve())
        assert str(folder.resolve()) in as_html.read_text()

    def test_format_defaults_to_the_search_export_format_setting(self, use_temp_db, tmp_path):
        _, source_id, _ = self._setup(use_temp_db, tmp_path)
        out = tmp_path / "out"

        result = runner.invoke(app, ["source", "list", str(source_id), "--export", str(out)])

        assert "(json)" in result.stdout
        json.loads(out.read_text())

    def test_html_escapes_file_names(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        _seed_files(db_path, folder)
        conn = Db.connect(db_path)
        conn.execute(
            "UPDATE document_index SET file_path = ? WHERE status = 'error'",
            (str(folder / "<b>x</b>.png"),),
        )
        conn.commit()
        conn.close()
        out = tmp_path / "o.html"

        runner.invoke(
            app, ["source", "list", str(folder), "--export", str(out), "--format", "html"]
        )

        assert "<b>x</b>.png" not in out.read_text()
        assert "&lt;b&gt;x&lt;/b&gt;.png" in out.read_text()

    def test_invalid_format_fails(self, use_temp_db, tmp_path):
        _, source_id, _ = self._setup(use_temp_db, tmp_path)

        result = runner.invoke(
            app,
            ["source", "list", str(source_id), "--export", str(tmp_path / "o"), "--format", "xml"],
        )

        assert result.exit_code == 1

    def test_format_without_export_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["source", "list", "--format", "json"])

        assert result.exit_code == 1


class TestSourceListSort:
    def test_files_default_to_filename_ascending(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        source_id, _ = _seed_files(db_path, folder)

        out = _unwrapped(runner.invoke(app, ["source", "list", str(source_id)]).stdout)

        assert out.index("scan.png") < out.index("sub/report.pdf")

    def test_files_sort_by_filename_descending(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        source_id, _ = _seed_files(db_path, folder)

        result = runner.invoke(app, ["source", "list", str(source_id), "--sort", "desc"])

        out = _unwrapped(result.stdout)
        assert out.index("sub/report.pdf") < out.index("scan.png")

    def test_files_sort_by_status(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        folder = tmp_path / "docs"
        folder.mkdir()
        source_id, _ = _seed_files(db_path, folder)

        result = runner.invoke(app, ["source", "list", str(source_id), "--sort-by", "status"])

        out = _unwrapped(result.stdout)
        assert out.index("error") < out.index("indexed")

    def test_sources_sort_by_id_descending(self, use_temp_db, tmp_path):
        use_temp_db()
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            runner.invoke(app, ["source", "add", str(tmp_path / name)])

        result = runner.invoke(app, ["source", "list", "--sort-by", "id", "--sort", "desc"])

        out = _unwrapped(result.stdout)
        assert out.index(_unwrapped(str(tmp_path / "b"))) < out.index(
            _unwrapped(str(tmp_path / "a"))
        )

    def test_invalid_sort_value_fails(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["source", "list", "--sort-by", "size"])

        assert result.exit_code != 0
