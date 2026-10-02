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
