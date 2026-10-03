import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_cli.search.pager import Pager
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import open_storage

runner = CliRunner()


def _flatten(output: str) -> str:
    """Collapse Rich's boxed, wrapped, colour-coded error text back onto one plain line."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(plain.replace("\u2502", " ").split())


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
    def test_search_reports_no_matches(self, use_temp_db):
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
        assert "Results: 1 match (engine: like)" in lines
        assert "File: /docs/invoice.pdf" in lines
        assert lines[lines.index("File: /docs/invoice.pdf") - 1] == "invoice.pdf"
        assert "Page: 1 of 1 [ocr]" in lines
        assert any(set(line) <= {"_"} for line in lines)
        assert any(line.startswith("|") and line.endswith("|") for line in lines)
        assert "amount due" in result.stdout

    def test_search_image_match_has_no_page_line(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_image(db_path, "/docs/scan.png", "Signed by John Doe")

        result = runner.invoke(app, ["search", "john doe"])

        assert result.exit_code == 0
        lines = result.stdout.splitlines()
        assert "File: /docs/scan.png" in lines
        assert not any(line.startswith("Page:") for line in lines)
        assert "[ocr]" in lines

    def test_search_shows_all_matches_without_prompting(self, use_temp_db):
        db_path = use_temp_db()
        for i in range(15):
            _seed_indexed_pdf(db_path, f"/docs/report-{i:02d}.pdf", "budget overview")

        result = runner.invoke(app, ["search", "budget"])

        assert result.exit_code == 0
        assert "Results: 15 matches (engine: like)" in result.stdout
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
        assert "Page: 1 of 3 [ocr]" in lines
        assert "Page: 3 of 3 [ocr]" in lines

    def test_search_export_requires_a_value(self, use_temp_db, tmp_path):
        use_temp_db()
        _seed_indexed_pdf(
            tmp_path / "vethuq.db", "/docs/invoice.pdf", "Total amount due: $1,200.00"
        )

        result = runner.invoke(app, ["search", "amount due", "--export"])

        assert result.exit_code == 2

    def test_search_export_defaults_to_json(self, use_temp_db, tmp_path):
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

    def test_search_export_html_links_the_file_path(self, use_temp_db, tmp_path):
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

    def test_search_export_rejects_unsupported_format(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        output = tmp_path / "out.xml"

        result = runner.invoke(
            app, ["search", "amount due", "--export", str(output), "--format", "xml"]
        )

        assert result.exit_code == 1
        assert not output.exists()

    def test_search_without_export_does_not_touch_output(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")

        result = runner.invoke(app, ["search", "amount due"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: like)" in result.stdout

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
        assert "Results: 3 matches (engine: like)" in result.stdout

    @pytest.mark.parametrize("source", ["native", "mixed"])
    def test_search_shows_page_source_tag(self, use_temp_db, source):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        conn = db_module.Db.connect(db_path)
        try:
            conn.execute("UPDATE pdf_pages SET source = ?", (source,))
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["search", "amount due"])

        assert f"Page: 1 of 1 [{source}]" in result.stdout.splitlines()


class TestSearchEngines:
    def test_engine_defaults_to_like_and_shows_it_in_the_header(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        result = runner.invoke(app, ["search", "mus"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: like)" in result.stdout

    def test_exact_engine_matches_as_typed(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        hit = runner.invoke(app, ["search", "Museum", "--engine", "exact"])
        miss = runner.invoke(app, ["search", "museum", "--engine", "exact"])

        assert "Results: 1 match (engine: exact, case-sensitive)" in hit.stdout
        assert "No matches found." in miss.stdout
        assert "--engine like" in miss.stdout  # the hint towards a looser engine

    def test_full_text_engine_matches_whole_words_and_prefixes(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        word = runner.invoke(app, ["search", "museums", "--engine", "full-text"])
        partial = runner.invoke(app, ["search", "mus", "--engine", "full-text"])
        prefix = runner.invoke(app, ["search", "mus*", "--engine", "full-text"])

        assert "Results: 1 match (engine: full-text)" in word.stdout
        assert "No matches found." in partial.stdout
        assert "Results: 1 match (engine: full-text)" in prefix.stdout

    def test_case_sensitive_flag_applies_to_like(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        loose = runner.invoke(app, ["search", "museum"])
        strict = runner.invoke(app, ["search", "museum", "--case-sensitive"])

        assert "Results: 1 match (engine: like)" in loose.stdout
        assert "No matches found." in strict.stdout

    def test_rejects_unknown_engine(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["search", "museum", "--engine", "nope"])

        assert result.exit_code == 2
        assert "full-text" in result.output

    def test_rejects_case_sensitive_full_text(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(
            app, ["search", "museum", "--engine", "full-text", "--case-sensitive"]
        )

        assert result.exit_code == 2
        assert "always case-insensitive" in _flatten(result.output)

    def test_rejects_case_insensitive_exact(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(
            app, ["search", "museum", "--engine", "exact", "--no-case-sensitive"]
        )

        assert result.exit_code == 2
        assert "always case-sensitive" in _flatten(result.output)

    def test_uses_engine_and_case_settings_when_flags_are_omitted(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")
        storage = open_storage(db_path)
        try:
            SearchSettings.set_engine(storage, "full-text")
            SearchSettings.set_case_sensitive(storage, True)
        finally:
            storage.close()

        from_setting = runner.invoke(app, ["search", "museum"])
        # A stored case-sensitive preference can't apply to full-text, so it must not
        # turn every default search into an error - only an explicit flag does.
        assert from_setting.exit_code == 0
        assert "Results: 1 match (engine: full-text)" in from_setting.stdout

        overridden = runner.invoke(app, ["search", "Museum", "--engine", "like"])
        assert "Results: 1 match (engine: like, case-sensitive)" in overridden.stdout
        turned_off = runner.invoke(
            app, ["search", "museum", "--engine", "like", "--no-case-sensitive"]
        )
        assert "Results: 1 match (engine: like)" in turned_off.stdout

    def test_export_records_engine_and_case_sensitivity(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")
        output = tmp_path / "out.json"

        result = runner.invoke(
            app, ["search", "Museum", "--engine", "exact", "--export", str(output)]
        )

        assert result.exit_code == 0
        payload = json.loads(output.read_text())
        assert payload["engine"] == "exact"
        assert payload["case_sensitive"] is True
