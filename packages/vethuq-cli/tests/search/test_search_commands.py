import json
from datetime import UTC, datetime
from pathlib import Path

import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_cli.search.pager import Pager

runner = CliRunner()


def _add_source(conn, path: str = "/docs") -> int:
    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES (?, 'folder', 'indexed', ?)",
        (path, now),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_document(conn) -> int:
    return conn.execute(
        "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
    ).lastrowid


def _seed_indexed_pdf(db_path, file_path: str, text: str, page_number: int = 1) -> int:
    conn = db_module.Db.connect(db_path)
    try:
        source_id = _add_source(conn, path=file_path + ".source")
        logical_document_id = _add_document(conn)
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'pdf', 'indexed')",
            (source_id, logical_document_id, file_path),
        ).lastrowid
        assert document_id is not None
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (?, ?, ?, 0.9)",
            (document_id, page_number, text),
        )
        conn.commit()
        return document_id
    finally:
        conn.close()


def _seed_indexed_image(db_path, file_path: str, text: str) -> int:
    conn = db_module.Db.connect(db_path)
    try:
        source_id = _add_source(conn, path=file_path + ".source")
        logical_document_id = _add_document(conn)
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'image', 'indexed')",
            (source_id, logical_document_id, file_path),
        ).lastrowid
        assert document_id is not None
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (?, ?, 0.9)",
            (document_id, text),
        )
        conn.commit()
        return document_id
    finally:
        conn.close()


class TestSearch:
    def test_search_reports_no_matches(self, use_temp_db, tmp_path, monkeypatch):
        use_temp_db()

        result = runner.invoke(app, ["search", "nothing"])

        assert result.exit_code == 0
        assert "No matches found." in result.stdout

    def test_search_prints_results_header_file_page_and_boxed_snippet(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        db_path = use_temp_db()
        _seed_indexed_pdf(
            db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00", page_number=1
        )

        result = runner.invoke(app, ["search", "amount due"])

        assert result.exit_code == 0
        lines = result.stdout.splitlines()
        assert "Results: 1 match" in lines
        assert "File: /docs/invoice.pdf" in lines
        assert "Page: 1 of 1" in lines
        assert any(set(line) <= {"_"} for line in lines)
        assert any(line.startswith("|") and line.endswith("|") for line in lines)
        assert "amount due" in result.stdout

    def test_search_image_match_has_no_page_line(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_image(db_path, "/docs/scan.png", "Signed by John Doe")

        result = runner.invoke(app, ["search", "john doe"])

        assert result.exit_code == 0
        lines = result.stdout.splitlines()
        assert "File: /docs/scan.png" in lines
        assert not any(line.startswith("Page:") for line in lines)

    def test_search_shows_all_matches_without_prompting(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        for i in range(15):
            _seed_indexed_pdf(db_path, f"/docs/report-{i:02d}.pdf", "budget overview")

        result = runner.invoke(app, ["search", "budget"])

        assert result.exit_code == 0
        assert "Results: 15 matches" in result.stdout
        assert "Show more?" not in result.stdout
        assert result.stdout.count("File: ") == 15

    def test_search_multiple_pages_of_same_file_print_file_once(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        db_path = use_temp_db()
        conn = db_module.Db.connect(db_path)
        try:
            source_id = _add_source(conn)
            logical_document_id = _add_document(conn)
            document_id = conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (?, ?, '/docs/report.pdf', 'pdf', 'indexed')",
                (source_id, logical_document_id),
            ).lastrowid
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, 1, ?, 0.9)",
                (document_id, "budget overview"),
            )
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, 2, ?, 0.9)",
                (document_id, "no match here"),
            )
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, 3, ?, 0.9)",
                (document_id, "final budget numbers"),
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["search", "budget"])

        lines = result.stdout.splitlines()
        assert lines.count("File: /docs/report.pdf") == 1
        assert "Page: 1 of 3" in lines
        assert "Page: 3 of 3" in lines

    def test_search_export_requires_a_value(self, use_temp_db, tmp_path, monkeypatch):
        use_temp_db()
        _seed_indexed_pdf(
            tmp_path / "vethuq.db", "/docs/invoice.pdf", "Total amount due: $1,200.00"
        )

        result = runner.invoke(app, ["search", "amount due", "--export"])

        assert result.exit_code == 2

    def test_search_export_defaults_to_json(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        output = tmp_path / "out.json"

        result = runner.invoke(app, ["search", "amount due", "--export", str(output)])

        assert result.exit_code == 0
        data = json.loads(output.read_text())
        assert data["query"] == "amount due"
        assert data["result_count"] == 1
        assert data["matches"][0]["file_path"] == "/docs/invoice.pdf"
        assert "amount due" in data["matches"][0]["matched_text"]
        assert "Exported 1 match(es)" in result.stdout
        assert "Results:" not in result.stdout
        assert "File:" not in result.stdout

    def test_search_export_html_links_the_file_path(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        output = tmp_path / "out.html"

        result = runner.invoke(
            app, ["search", "amount due", "--export", str(output), "--format", "html"]
        )

        assert result.exit_code == 0
        html = output.read_text()
        assert Path("/docs/invoice.pdf").resolve().as_uri() in html
        assert "<mark>amount due</mark>" in html

    def test_search_export_rejects_unsupported_format(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        output = tmp_path / "out.xml"

        result = runner.invoke(
            app, ["search", "amount due", "--export", str(output), "--format", "xml"]
        )

        assert result.exit_code == 1
        assert not output.exists()

    def test_search_without_export_does_not_touch_output(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")

        result = runner.invoke(app, ["search", "amount due"])

        assert result.exit_code == 0
        assert "Results: 1 match" in result.stdout

    def test_search_pager_export_prompts_and_writes_file(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        monkeypatch.setattr(Pager, "page", lambda rendered, on_export: on_export())
        output = tmp_path / "out.json"

        result = runner.invoke(app, ["search", "amount due"], input=f"{output}\n\n")

        assert result.exit_code == 0
        assert output.exists()
        assert json.loads(output.read_text())
        assert "Exported" in result.stdout

    def test_search_pager_export_cancelled_on_blank_filename(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        monkeypatch.setattr(Pager, "page", lambda rendered, on_export: on_export())

        result = runner.invoke(app, ["search", "amount due"], input="\n")

        assert result.exit_code == 0
        assert "Export cancelled." in result.stdout

    def test_search_different_files_each_get_their_own_file_line(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        db_path = use_temp_db()
        conn = db_module.Db.connect(db_path)
        try:
            source_id = _add_source(conn)
            logical_document_id = _add_document(conn)
            document_id = conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (?, ?, '/docs/a.pdf', 'pdf', 'indexed')",
                (source_id, logical_document_id),
            ).lastrowid
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, 1, ?, 0.9)",
                (document_id, "budget one"),
            )
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, 2, ?, 0.9)",
                (document_id, "budget two"),
            )
            conn.commit()
        finally:
            conn.close()
        _seed_indexed_pdf(db_path, "/docs/b.pdf", "budget three")

        result = runner.invoke(app, ["search", "budget"])

        lines = result.stdout.splitlines()
        assert lines.count("File: /docs/a.pdf") == 1
        assert lines.count("File: /docs/b.pdf") == 1
        assert "Results: 3 matches" in result.stdout
