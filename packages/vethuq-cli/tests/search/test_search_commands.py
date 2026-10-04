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


_BOX_CHARS = "─│┌┐└┘╭╮╰╯├┤"


def _content_lines(output: str) -> list[str]:
    """`output`'s lines with the panel borders (and the padding inside them) stripped."""
    stripped = (line.strip(_BOX_CHARS + " ") for line in output.splitlines())
    return [line for line in stripped if line]


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

        result = runner.invoke(app, ["search", "amount due", "--engine", "like"])

        assert result.exit_code == 0
        lines = _content_lines(result.stdout)
        assert "Search Results: 1 match (engine: like)" in lines
        assert "File: /docs/invoice.pdf" in lines
        assert lines[lines.index("File: /docs/invoice.pdf") - 1] == "invoice.pdf"
        assert "Page: 1 of 1 [ocr]" in lines
        assert "Total amount due: $1,200.00" in lines  # the snippet, in its own box

    def test_search_image_match_has_no_page_line(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_image(db_path, "/docs/scan.png", "Signed by John Doe")

        result = runner.invoke(app, ["search", "john doe", "--engine", "like"])

        assert result.exit_code == 0
        lines = _content_lines(result.stdout)
        assert "File: /docs/scan.png" in lines
        assert not any(line.startswith("Page:") for line in lines)
        assert "[ocr]" in lines

    def test_search_shows_all_matches_without_prompting(self, use_temp_db):
        db_path = use_temp_db()
        for i in range(15):
            _seed_indexed_pdf(db_path, f"/docs/report-{i:02d}.pdf", "budget overview")

        result = runner.invoke(app, ["search", "budget", "--engine", "like"])

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

        result = runner.invoke(app, ["search", "budget", "--engine", "like"])

        lines = _content_lines(result.stdout)
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

        result = runner.invoke(app, ["search", "amount due", "--engine", "like"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: like)" in result.stdout

    def test_search_pager_export_prompts_and_writes_file(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00")
        monkeypatch.setattr(Pager, "page", lambda rendered, on_export, help_text=None: on_export())
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
        monkeypatch.setattr(Pager, "page", lambda rendered, on_export, help_text=None: on_export())

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

        result = runner.invoke(app, ["search", "budget", "--engine", "like"])

        lines = _content_lines(result.stdout)
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

        result = runner.invoke(app, ["search", "amount due", "--engine", "like"])

        assert f"Page: 1 of 1 [{source}]" in _content_lines(result.stdout)


class TestSearchEngines:
    def test_engine_defaults_to_all_and_shows_it_in_the_header(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        result = runner.invoke(app, ["search", "mus"])

        assert result.exit_code == 0
        assert "Results: 1 page (engine: all)" in result.stdout

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

        loose = runner.invoke(app, ["search", "museum", "--engine", "like"])
        strict = runner.invoke(app, ["search", "museum", "--engine", "like", "--case-sensitive"])

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

    def test_fuzzy_engine_finds_misspellings_and_shows_similarity(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Muzeum today")

        result = runner.invoke(app, ["search", "Museum", "--engine", "fuzzy"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: fuzzy, threshold 80%)" in result.stdout
        assert "similarity 83%" in result.stdout
        assert "Muzeum" in result.stdout

    def test_fuzzy_threshold_and_fuzziness_flags(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museurn today")

        balanced = runner.invoke(app, ["search", "Museum", "--engine", "fuzzy"])
        loose = runner.invoke(
            app, ["search", "Museum", "--engine", "fuzzy", "--fuzziness", "loose"]
        )
        numeric = runner.invoke(
            app, ["search", "Museum", "--engine", "fuzzy", "--threshold", "0.7"]
        )

        assert "No matches found." in balanced.stdout
        assert "--fuzziness loose" in balanced.stdout  # the hint towards a looser setting
        assert "Results: 1 match (engine: fuzzy, threshold 65%)" in loose.stdout
        assert "Results: 1 match (engine: fuzzy, threshold 70%)" in numeric.stdout

    def test_fuzzy_uses_the_stored_threshold_and_engine(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museurn today")
        storage = open_storage(db_path)
        try:
            SearchSettings.set_engine(storage, "fuzzy")
            SearchSettings.set_fuzzy_threshold(storage, "loose")
        finally:
            storage.close()

        result = runner.invoke(app, ["search", "Museum"])
        overridden = runner.invoke(app, ["search", "Museum", "--fuzziness", "strict"])

        assert "Results: 1 match (engine: fuzzy, threshold 65%)" in result.stdout
        assert "No matches found." in overridden.stdout

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--engine", "like", "--threshold", "0.8"], "Only the fuzzy and noise-fuzzy engines"),
            (
                ["--engine", "full-text", "--fuzziness", "loose"],
                "Only the fuzzy and noise-fuzzy engines",
            ),
            (["--engine", "fuzzy", "--threshold", "0"], "above 0"),
            (["--engine", "fuzzy", "--threshold", "150"], "above 0"),
            (["--engine", "fuzzy", "--fuzziness", "sloppy"], "not one of"),
            (["--engine", "fuzzy", "--fuzziness", "loose", "--threshold", "0.7"], "not both"),
        ],
    )
    def test_rejects_unusable_threshold_options(self, use_temp_db, args, message):
        use_temp_db()

        result = runner.invoke(app, ["search", "museum", *args])

        assert result.exit_code == 2
        assert message in _flatten(result.output)

    def test_stored_threshold_is_ignored_by_other_engines(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")
        storage = open_storage(db_path)
        try:
            SearchSettings.set_fuzzy_threshold(storage, "loose")
        finally:
            storage.close()

        result = runner.invoke(app, ["search", "museum", "--engine", "like"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: like)" in result.stdout

    def test_fuzzy_export_records_the_threshold(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Muzeum today")
        output = tmp_path / "out.json"

        result = runner.invoke(
            app,
            [
                "search",
                "Museum",
                "--engine",
                "fuzzy",
                "--threshold",
                "0.75",
                "--export",
                str(output),
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(output.read_text())
        assert (payload["engine"], payload["threshold"]) == ("fuzzy", 0.75)
        assert payload["matches"][0]["score"] > 0.8

    _CONTRACT = "The payment is due within thirty days, subject to the termination clause."

    def test_proximity_finds_terms_close_together(self, use_temp_db):
        _seed_indexed_pdf(use_temp_db(), "/docs/contract.pdf", self._CONTRACT)

        result = runner.invoke(app, ["search", "payment termination", "--engine", "proximity"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: proximity, within 10 words)" in result.stdout
        assert "payment is due within thirty days, subject to the termination" in _flatten(
            result.stdout.replace("|", " ")
        )

    def test_proximity_distance_flag_accepts_numbers_and_presets(self, use_temp_db):
        # 8 words between the terms
        _seed_indexed_pdf(use_temp_db(), "/docs/contract.pdf", self._CONTRACT)
        base = ["search", "payment termination", "--engine", "proximity"]

        tight = runner.invoke(app, [*base, "--distance", "tight"])
        seven = runner.invoke(app, [*base, "--distance", "7"])
        eight = runner.invoke(app, [*base, "--distance", "8"])
        loose = runner.invoke(app, [*base, "--distance", "loose"])

        assert "No matches found." in tight.stdout
        assert "--distance loose" in tight.stdout  # the hint towards a looser distance
        assert "No matches found." in seven.stdout
        assert "within 8 words" in eight.stdout
        assert "within 30 words" in loose.stdout

    def test_proximity_uses_the_stored_distance_and_engine(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/contract.pdf", self._CONTRACT)
        storage = open_storage(db_path)
        try:
            SearchSettings.set_engine(storage, "proximity")
            SearchSettings.set_proximity_distance(storage, "tight")
        finally:
            storage.close()

        stored = runner.invoke(app, ["search", "payment termination"])
        overridden = runner.invoke(app, ["search", "payment termination", "--distance", "12"])

        assert "No matches found." in stored.stdout
        assert "within 12 words" in overridden.stdout

    def test_proximity_needs_two_terms(self, use_temp_db):
        _seed_indexed_pdf(use_temp_db(), "/docs/contract.pdf", self._CONTRACT)

        result = runner.invoke(app, ["search", "payment", "--engine", "proximity"])

        assert result.exit_code == 2
        assert "at least two" in _flatten(result.output)

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--engine", "like", "--distance", "5"], "Only the proximity engine"),
            (["--engine", "fuzzy", "--distance", "loose"], "Only the proximity engine"),
            (["--engine", "proximity", "--distance", "0"], "from 1 to 100"),
            (["--engine", "proximity", "--distance", "101"], "from 1 to 100"),
            (["--engine", "proximity", "--distance", "nope"], "from 1 to 100"),
            (
                ["--engine", "proximity", "--threshold", "80%"],
                "Only the fuzzy and noise-fuzzy engines",
            ),
            (["--engine", "proximity", "--case-sensitive"], "always case-insensitive"),
            (["--engine", "fuzzy", "--distance", "5"], "Only the proximity engine"),
        ],
    )
    def test_rejects_unusable_distance_options(self, use_temp_db, args, message):
        use_temp_db()

        result = runner.invoke(app, ["search", "payment termination", *args])

        assert result.exit_code == 2
        assert message in _flatten(result.output)

    def test_stored_distance_is_ignored_by_other_engines(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/contract.pdf", self._CONTRACT)
        storage = open_storage(db_path)
        try:
            SearchSettings.set_proximity_distance(storage, "tight")
        finally:
            storage.close()

        result = runner.invoke(app, ["search", "payment", "--engine", "like"])

        assert result.exit_code == 0
        assert "Results: 1 match (engine: like)" in result.stdout

    def test_proximity_export_records_the_distance(self, use_temp_db, tmp_path):
        _seed_indexed_pdf(use_temp_db(), "/docs/contract.pdf", self._CONTRACT)
        output = tmp_path / "out.json"

        result = runner.invoke(
            app,
            [
                "search",
                "payment termination",
                "--engine",
                "proximity",
                "--distance",
                "12",
                "--export",
                str(output),
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(output.read_text())
        assert (payload["engine"], payload["distance"]) == ("proximity", 12)
        assert "payment is due" in payload["matches"][0]["matched_text"]

    def test_fuzzy_threshold_accepts_percentages(self, use_temp_db):
        _seed_indexed_pdf(use_temp_db(), "/docs/museum.pdf", "Visit the Museurn today")
        base = ["search", "Museum", "--engine", "fuzzy", "--threshold"]

        percent = runner.invoke(app, [*base, "70%"])
        whole = runner.invoke(app, [*base, "70"])
        ratio = runner.invoke(app, [*base, "0.7"])
        strict = runner.invoke(app, [*base, "75%"])

        for result in (percent, whole, ratio):
            assert "Results: 1 match (engine: fuzzy, threshold 70%)" in result.stdout
        assert "No matches found." in strict.stdout


def _seed_pages(db_path, path: str, pages: list[str]) -> None:
    for number, text in enumerate(pages, start=1):
        if number == 1:
            _seed_indexed_pdf(db_path, path, text)
            continue
        conn = db_module.Db.connect(db_path)
        try:
            document_id = conn.execute(
                "SELECT id FROM document_index WHERE file_path = ?", (path,)
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, ?, ?, 0.9)",
                (document_id, number, text),
            )
            conn.commit()
        finally:
            conn.close()


class TestSearchLookalikes:
    def test_like_finds_look_alike_spellings_both_ways_when_asked(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "the p@55w0rd is secret")
        _seed_indexed_pdf(db_path, "/docs/b.pdf", "the password is secret")

        off = runner.invoke(app, ["search", "password", "--engine", "like"])
        plain = runner.invoke(
            app, ["search", "password", "--engine", "like", "--leet-level", "basic"]
        )
        disguised = runner.invoke(
            app, ["search", "p@55w0rd", "--engine", "like", "--leet-level", "basic"]
        )

        assert "Results: 1 match (engine: like)" in off.stdout
        assert "Results: 2 matches (engine: like, leet level basic)" in plain.stdout
        assert "p@55w0rd" in plain.stdout and "password" in plain.stdout
        assert "Results: 2 matches (engine: like, leet level basic)" in disguised.stdout

    def test_honours_case_sensitive(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say H3LL0 and h3ll0")

        loose = runner.invoke(app, ["search", "hello", "--engine", "like", "--leet-level", "basic"])
        strict = runner.invoke(
            app,
            ["search", "hello", "--engine", "like", "--leet-level", "basic", "--case-sensitive"],
        )

        assert "Results: 2 matches (engine: like, leet level basic)" in loose.stdout
        assert "Results: 1 match (engine: like, case-sensitive" in strict.stdout

    def test_the_stored_setting_is_the_default_and_the_flag_beats_it(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "a 9ame day")

        basic = runner.invoke(app, ["search", "game", "--engine", "like", "--leet-level", "basic"])
        runner.invoke(app, ["settings", "search", "normalize", "leetspeak", "set", "standard"])
        stored = runner.invoke(app, ["search", "game", "--engine", "like"])
        overridden = runner.invoke(
            app, ["search", "game", "--engine", "like", "--leet-level", "off"]
        )

        assert "No matches found." in basic.stdout
        assert "Results: 1 match (engine: like, leet level standard)" in stored.stdout
        assert "No matches found." in overridden.stdout

    def test_the_combined_search_labels_a_disguised_page_lookalike(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h3ll0 to all")

        result = runner.invoke(app, ["search", "hello"])

        assert result.exit_code == 0
        lines = _content_lines(result.stdout)
        assert "Page: 1 of 1 [ocr] [Contains · look-alike]  also: Obscured" in lines
        assert "say h3ll0 to all" in lines

    def test_the_combined_search_uses_the_flag_and_the_setting(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "a 9ame day")

        basic = runner.invoke(app, ["search", "game"])
        standard = runner.invoke(app, ["search", "game", "--leet-level", "standard"])
        runner.invoke(app, ["settings", "search", "normalize", "leetspeak", "set", "off"])
        off = runner.invoke(app, ["search", "hello"])

        assert "[Contains · look-alike]" not in basic.stdout  # a 9 is a g only from standard on
        assert "[Contains · look-alike]" in standard.stdout
        assert "[Contains · look-alike]" not in off.stdout

    def test_leet_level_flag_is_validated(self, use_temp_db):
        use_temp_db()

        invalid = runner.invoke(
            app, ["search", "hello", "--engine", "like", "--leet-level", "insane"]
        )
        wrong_engine = runner.invoke(
            app, ["search", "hello", "--engine", "fuzzy", "--leet-level", "basic"]
        )

        assert invalid.exit_code != 0
        assert "off, basic, standard, extended" in _flatten(invalid.output)
        assert "--leet-level" in _flatten(invalid.output)
        assert wrong_engine.exit_code != 0
        assert "Only the like and noise-fuzzy engines have a leetspeak level" in _flatten(
            wrong_engine.output
        )

    def test_export_records_the_leet_level(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "a 9ame day")
        as_json = tmp_path / "out.json"
        as_html = tmp_path / "out.html"
        base = ["search", "game", "--engine", "like", "--leet-level", "standard"]

        runner.invoke(app, [*base, "--export", str(as_json)])
        runner.invoke(app, [*base, "--export", str(as_html), "--format", "html"])

        assert json.loads(as_json.read_text())["leet_level"] == "standard"
        assert "leet level standard" in as_html.read_text()

    def test_leetspeak_is_no_longer_an_engine(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["search", "hello", "--engine", "leetspeak"])

        assert result.exit_code != 0
        assert "not one of" in _flatten(result.output)

    def test_other_engines_still_reject_fuzzy_and_proximity_options(self, use_temp_db):
        use_temp_db()

        threshold = runner.invoke(
            app, ["search", "hello", "--engine", "like", "--threshold", "0.8"]
        )

        assert threshold.exit_code != 0 and "Only the fuzzy and noise-fuzzy engines" in _flatten(
            threshold.output
        )


class TestSearchNormalize:
    def test_unicode_folds_accents_for_like(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "visit the café today")

        off = runner.invoke(app, ["search", "cafe", "--engine", "like"])
        full = runner.invoke(
            app, ["search", "cafe", "--engine", "like", "--normalize", "unicode=full"]
        )

        assert "No matches found." in off.stdout
        assert "Results: 1 match (engine: like, unicode full)" in full.stdout
        assert "café" in full.stdout

    def test_several_normalizations_in_one_flag_or_many(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "visit the C@FÉ today")

        one = runner.invoke(
            app,
            ["search", "cafe", "--engine", "like", "--normalize", "unicode=full,leetspeak=basic"],
        )
        many = runner.invoke(
            app,
            ["search", "cafe", "--engine", "like"]
            + ["--normalize", "unicode=full", "--normalize", "leet=basic"],
        )
        strict = runner.invoke(
            app,
            ["search", "cafe", "--engine", "like"]
            + ["--normalize", "unicode=full,leetspeak=basic,case=match"],
        )

        for result in (one, many):
            assert "Results: 1 match (engine: like, leet level basic, unicode full)" in (
                result.stdout
            )
        assert "No matches found." in strict.stdout  # the capitals are another case

    def test_case_names_the_same_flags(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say HELLO to all")

        ignore = runner.invoke(
            app, ["search", "hello", "--engine", "like", "--normalize", "case=ignore"]
        )
        match = runner.invoke(
            app, ["search", "hello", "--engine", "like", "--normalize", "case=match"]
        )

        assert "Results: 1 match (engine: like)" in ignore.stdout
        assert "No matches found." in match.stdout

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--normalize", "stemming=on"], "NAME=VALUE"),
            (["--normalize", "unicode"], "NAME=VALUE"),
            (["--normalize", "unicode="], "NAME=VALUE"),
            (["--normalize", "case=sometimes"], "ignore, match"),
            (["--normalize", "unicode=nfd"], "off, basic, full"),
            (["--normalize", "leetspeak=insane"], "off, basic, standard, extended"),
            (["--normalize", "case=match", "--case-sensitive"], "case is given twice"),
            (["--normalize", "leetspeak=basic", "--leet-level", "off"], "leetspeak is given"),
            (["--normalize", "unicode=full,unicode=basic"], "unicode is given twice"),
        ],
    )
    def test_the_flag_is_validated(self, use_temp_db, args, message):
        use_temp_db()

        result = runner.invoke(app, ["search", "hello", "--engine", "like", *args])

        assert result.exit_code != 0
        assert message in _flatten(result.output)

    def test_engines_without_a_unicode_setting_reject_it(self, use_temp_db):
        use_temp_db()

        for engine in ("lexical", "full-text", "proximity"):
            result = runner.invoke(
                app, ["search", "hello world", "--engine", engine, "--normalize", "unicode=full"]
            )
            assert result.exit_code != 0
            assert "Only the like, exact, fuzzy and noise-fuzzy engines" in _flatten(result.output)

    def test_the_stored_setting_applies_but_never_to_exact(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "visit the Café today")
        runner.invoke(app, ["settings", "search", "normalize", "unicode", "set", "full"])

        like = runner.invoke(app, ["search", "cafe", "--engine", "like"])
        exact = runner.invoke(app, ["search", "Cafe", "--engine", "exact"])
        exact_asked = runner.invoke(
            app, ["search", "Cafe", "--engine", "exact", "--normalize", "unicode=full"]
        )

        assert "unicode full" in like.stdout and "Café" in like.stdout
        assert "No matches found." in exact.stdout
        assert "Café" in exact_asked.stdout

    def test_fuzzy_and_noise_fuzzy_take_it_too(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "a visit to the Café today")

        fuzzy = runner.invoke(app, ["search", "Cafe", "--engine", "fuzzy"])
        noise = runner.invoke(app, ["search", "Cafe", "--engine", "noise-fuzzy"])
        basic = runner.invoke(
            app, ["search", "Cafe", "--engine", "fuzzy", "--normalize", "unicode=basic"]
        )

        # They fold accents by default, so it's only shown when it isn't the default.
        assert "Café" in fuzzy.stdout and "unicode" not in fuzzy.stdout
        assert "Café" in noise.stdout
        assert "No matches found." in basic.stdout

    def test_the_combined_search_uses_it(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "the \uff21\uff22\uff23 sign")

        off = runner.invoke(app, ["search", "abc", "--normalize", "unicode=off"])
        full = runner.invoke(app, ["search", "abc"])

        assert "No matches found." in off.stdout
        assert "\uff21\uff22\uff23" in full.stdout

    def test_export_records_the_unicode_level(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "visit the café today")
        as_json = tmp_path / "out.json"
        as_html = tmp_path / "out.html"
        base = ["search", "cafe", "--engine", "like", "--normalize", "unicode=full"]

        runner.invoke(app, [*base, "--export", str(as_json)])
        runner.invoke(app, [*base, "--export", str(as_html), "--format", "html"])

        assert json.loads(as_json.read_text())["unicode"] == "full"
        assert "unicode full" in as_html.read_text()


class TestSearchNoiseFuzzy:
    def test_finds_each_kind_of_hiding(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h3ll0 and helo and he llo to all")

        result = runner.invoke(app, ["search", "hello", "--engine", "noise-fuzzy"])

        assert result.exit_code == 0
        assert "Results: 3 matches (engine: noise-fuzzy, threshold 80%" in result.stdout
        for text in ("h3ll0", "helo", "he llo"):
            assert text in result.stdout

    def test_the_header_shows_threshold_level_and_noise(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h3ll0 to all")

        result = runner.invoke(
            app, ["search", "hello", "--engine", "noise-fuzzy", "--noise", "medium"]
        )

        # (the panel title is cut off at 80 columns; the export keeps every option)
        assert "engine: noise-fuzzy, threshold 80%, leet level bas" in _flatten(result.stdout)

    def test_noise_flag_beats_the_setting(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h..e llo to all")

        low = runner.invoke(app, ["search", "hello", "--engine", "noise-fuzzy"])
        medium = runner.invoke(
            app, ["search", "hello", "--engine", "noise-fuzzy", "--noise", "medium"]
        )
        runner.invoke(app, ["settings", "search", "noise-fuzzy", "noise", "set", "medium"])
        stored = runner.invoke(app, ["search", "hello", "--engine", "noise-fuzzy"])
        overridden = runner.invoke(
            app, ["search", "hello", "--engine", "noise-fuzzy", "--noise", "low"]
        )

        assert "No matches found." in low.stdout
        assert "--noise medium" in low.stdout  # the hint towards more noise
        assert "h..e llo" in medium.stdout and "h..e llo" in stored.stdout
        assert "No matches found." in overridden.stdout

    def test_fuzziness_and_leet_level_flags_apply(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "a 9ame and a Museurn")

        game = runner.invoke(
            app, ["search", "game", "--engine", "noise-fuzzy", "--fuzziness", "strict"]
        )
        standard = runner.invoke(
            app,
            ["search", "game", "--engine", "noise-fuzzy", "--fuzziness", "strict"]
            + ["--leet-level", "standard"],
        )
        loose = runner.invoke(
            app, ["search", "Museum", "--engine", "noise-fuzzy", "--threshold", "0.65"]
        )

        assert "No matches found." in game.stdout
        assert "9ame" in standard.stdout and "threshold 90%, leet level sta" in standard.stdout
        assert "Museurn" in loose.stdout and "threshold 65%" in loose.stdout

    def test_honours_case_sensitive(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say HELLO to all")

        loose = runner.invoke(app, ["search", "hello", "--engine", "noise-fuzzy"])
        strict = runner.invoke(
            app, ["search", "hello", "--engine", "noise-fuzzy", "--case-sensitive"]
        )

        assert "HELLO" in loose.stdout
        assert "No matches found." in strict.stdout

    def test_in_the_combined_search_it_is_labelled_obscured(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h.ell0 to all")

        result = runner.invoke(app, ["search", "hello"])

        assert result.exit_code == 0
        lines = _content_lines(result.stdout)
        assert "Page: 1 of 1 [ocr] [Obscured]" in lines
        assert "say h.ell0 to all" in lines

    def test_the_noise_flag_reaches_the_combined_search(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h..e llo to all")

        default = runner.invoke(app, ["search", "hello"])
        medium = runner.invoke(app, ["search", "hello", "--noise", "medium"])

        assert "No matches found." in default.stdout
        assert "[Obscured]" in medium.stdout

    def test_noise_flag_is_validated(self, use_temp_db):
        use_temp_db()

        invalid = runner.invoke(
            app, ["search", "hello", "--engine", "noise-fuzzy", "--noise", "loud"]
        )
        wrong_engine = runner.invoke(app, ["search", "hello", "--engine", "like", "--noise", "low"])

        assert invalid.exit_code != 0 and "noise must be one of" in _flatten(invalid.output)
        assert "--noise" in _flatten(invalid.output)
        assert wrong_engine.exit_code != 0
        assert "Only the noise-fuzzy engine has a noise level" in _flatten(wrong_engine.output)

    def test_a_distance_is_an_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(
            app, ["search", "hello", "--engine", "noise-fuzzy", "--distance", "5"]
        )

        assert result.exit_code != 0
        assert "Only the proximity engine" in _flatten(result.output)

    def test_export_records_threshold_level_and_noise(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/a.pdf", "say h3ll0 to all")
        as_json = tmp_path / "out.json"
        as_html = tmp_path / "out.html"

        runner.invoke(
            app,
            ["search", "hello", "--engine", "noise-fuzzy", "--noise", "medium"]
            + ["--export", str(as_json)],
        )
        runner.invoke(
            app,
            ["search", "hello", "--engine", "noise-fuzzy", "--noise", "medium"]
            + ["--export", str(as_html), "--format", "html"],
        )

        payload = json.loads(as_json.read_text())
        assert payload["engine"] == "noise-fuzzy"
        assert (payload["threshold"], payload["leet_level"], payload["noise"]) == (
            0.8,
            "basic",
            "medium",
        )
        assert "noise medium" in as_html.read_text()


class TestSearchAll:
    def test_labels_each_page_with_how_it_was_found(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/exact.pdf", "Visit the Museum today")

        result = runner.invoke(app, ["search", "Museum"])

        assert result.exit_code == 0
        lines = _content_lines(result.stdout)
        assert "Search Results: 1 page (engine: all)" in lines
        assert "Page: 1 of 1 [ocr] [Exact]  also: Contains, Relevant, Word, Similar," in lines
        assert "Obscured" in lines  # the label wraps rather than cutting off

    def test_ranks_pages_exact_then_contains_then_word_then_similar(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/d_similar.pdf", "the Muzeum guide")
        _seed_indexed_pdf(db_path, "/docs/c_word.pdf", "he runs fast")
        _seed_indexed_pdf(db_path, "/docs/b_contains.pdf", "the MUSEUM guide")
        _seed_indexed_pdf(db_path, "/docs/a_exact.pdf", "the Museum guide")

        museum = runner.invoke(app, ["search", "Museum"])
        running = runner.invoke(app, ["search", "running"])

        order = [line for line in _content_lines(museum.stdout) if line.startswith("File: ")]
        assert order == [
            "File: /docs/a_exact.pdf",
            "File: /docs/b_contains.pdf",
            "File: /docs/d_similar.pdf",
        ]
        assert "[Exact]" in museum.stdout and "[Contains]" in museum.stdout
        assert "[Similar 83%]" in museum.stdout
        assert "[Word]" in running.stdout

    def test_labels_a_weaker_hit_and_caps_the_boxes_per_page(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(
            db_path,
            "/docs/museum.pdf",
            "the Museum; a Muzeum; the Museum; a Muzeum; the Museum; a Muzeum",
        )

        result = runner.invoke(app, ["search", "Museum"])

        lines = _content_lines(result.stdout)
        assert "Search Results: 1 page (engine: all)" in lines
        # 6 hits, best first: the three Exact ones fill the three boxes, the weaker are counted
        assert lines.count("[Similar 83%]") == 0
        assert "+3 more matches on this page" in lines

    def test_labels_hits_found_less_strictly_than_the_pages_best(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "the Museum; a Muzeum; a Muzeum")

        result = runner.invoke(app, ["search", "Museum"])

        lines = _content_lines(result.stdout)
        # the first box is the page's own [Exact] label, the other two are labelled
        assert lines.count("[Similar 83%]") == 2
        assert not any(line.startswith("+") and "more" in line for line in lines)

    def test_uses_options_where_the_engine_can_and_never_errors(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "the MUSEUM and the Museurn")

        strict = runner.invoke(app, ["search", "museum", "--case-sensitive"])
        loose = runner.invoke(app, ["search", "Museum", "--threshold", "65%"])
        near = runner.invoke(app, ["search", "MUSEUM Museurn", "--distance", "loose"])

        for result in (strict, loose, near):
            assert result.exit_code == 0
        # case-sensitive reaches like and fuzzy only, so full-text alone is left to find MUSEUM
        assert "[Word]" in strict.stdout and "(engine: all, case-sensitive)" in strict.stdout
        assert "Museurn" in loose.stdout
        assert "[Near]" in near.stdout

    def test_reports_no_matches(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        result = runner.invoke(app, ["search", "zebra"])

        assert result.exit_code == 0
        assert "No matches found." in result.stdout

    def test_skips_proximity_for_a_single_word(self, use_temp_db):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "Visit the Museum today")

        result = runner.invoke(app, ["search", "Museum", "--engine", "all"])

        assert result.exit_code == 0
        assert "Near" not in result.stdout

    def test_export_lists_each_hit_with_its_engines(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _seed_indexed_pdf(db_path, "/docs/museum.pdf", "the Museum and a Muzeum")
        as_json = tmp_path / "out.json"
        as_html = tmp_path / "out.html"

        first = runner.invoke(app, ["search", "Museum", "--export", str(as_json)])
        second = runner.invoke(
            app, ["search", "Museum", "--export", str(as_html), "--format", "html"]
        )

        assert first.exit_code == 0 and second.exit_code == 0
        payload = json.loads(as_json.read_text())
        assert payload["engine"] == "all"
        assert [m["engine"] for m in payload["matches"]] == ["exact", "fuzzy"]
        assert "Muzeum" in payload["matches"][1]["matched_text"]
        assert payload["matches"][0]["matched_by"] == [
            "exact",
            "like",
            "lexical",
            "full-text",
            "fuzzy",
            "noise-fuzzy",
        ]
        html_text = as_html.read_text()
        assert "engine: all" in html_text
        assert ">Exact<" in html_text and ">Similar 83%<" in html_text

    def test_single_engine_keeps_the_flat_per_match_output(self, use_temp_db):
        db_path = use_temp_db()
        _seed_pages(db_path, "/docs/museum.pdf", ["the Museum", "the Museum again"])

        result = runner.invoke(app, ["search", "Museum", "--engine", "exact"])

        assert "Results: 2 matches (engine: exact, case-sensitive)" in result.stdout
        assert "[Exact]" not in result.stdout  # single-engine results aren't labelled
