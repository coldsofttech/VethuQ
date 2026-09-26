import os
from datetime import UTC, datetime
from functools import partial

import pytest
import vethuq_cli.search as search_module
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app

runner = CliRunner()


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    monkeypatch.setattr(search_module, "connect", partial(db_module.connect, db_path))
    return db_path


def _add_source(conn, path: str = "/docs") -> int:
    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES (?, 'folder', 'indexed', ?)",
        (path, now),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _seed_indexed_pdf(db_path, file_path: str, text: str, page_number: int = 1) -> int:
    conn = db_module.connect(db_path)
    try:
        source_id = _add_source(conn, path=file_path + ".source")
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, file_path, file_type, status) "
            "VALUES (?, ?, 'pdf', 'indexed')",
            (source_id, file_path),
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
    conn = db_module.connect(db_path)
    try:
        source_id = _add_source(conn, path=file_path + ".source")
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, file_path, file_type, status) "
            "VALUES (?, ?, 'image', 'indexed')",
            (source_id, file_path),
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


def test_page_prints_everything_directly_when_not_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(search_module.sys.stdout, "isatty", lambda: False)

    search_module._page("line one\nline two\nline three")

    out = capsys.readouterr().out
    assert out.splitlines() == ["line one", "line two", "line three"]


def test_page_reveals_one_more_line_on_down_and_quits_on_q(monkeypatch):
    # The status prompt is erased and redrawn via raw ANSI cursor codes meant
    # for a real terminal to interpret, so a plain stdout capture can't tell
    # what ends up "on screen" - recording each echoed line's content instead
    # keeps this test independent of that rendering detail.
    monkeypatch.setattr(search_module.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        search_module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 3))
    )
    keys = iter(["down", "quit"])
    monkeypatch.setattr(search_module, "_read_key_windows", lambda: next(keys))
    monkeypatch.setattr(search_module, "_read_key_posix", lambda: next(keys))
    echoed = []
    monkeypatch.setattr(
        search_module.typer, "echo", lambda message="", nl=True: echoed.append(message)
    )

    with pytest.raises(KeyboardInterrupt):
        search_module._page("l1\nl2\nl3\nl4\nl5")

    # terminal_size.lines=3 reserves one line for the status prompt, so the
    # first screen is 2 lines; pressing "down" reveals exactly one more.
    content_lines = [message for message in echoed if message in ("l1", "l2", "l3", "l4", "l5")]
    assert content_lines == ["l1", "l2", "l3"]


def test_page_stops_without_prompting_when_content_fits_one_screen(monkeypatch, capsys):
    monkeypatch.setattr(search_module.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        search_module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 10))
    )

    def _fail():
        raise AssertionError("should not read a key when everything already fits")

    monkeypatch.setattr(search_module, "_read_key_windows", lambda: _fail())
    monkeypatch.setattr(search_module, "_read_key_posix", lambda: _fail())

    search_module._page("l1\nl2\nl3")

    assert capsys.readouterr().out.splitlines() == ["l1", "l2", "l3"]


def test_search_reports_no_matches(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["search", "nothing"])

    assert result.exit_code == 0
    assert "No matches found." in result.stdout


def test_search_prints_results_header_file_page_and_boxed_snippet(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _seed_indexed_pdf(db_path, "/docs/invoice.pdf", "Total amount due: $1,200.00", page_number=1)

    result = runner.invoke(app, ["search", "amount due"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "Results: 1 match" in lines
    assert "File: /docs/invoice.pdf" in lines
    assert "Page: 1 of 1" in lines
    assert any(set(line) <= {"_"} for line in lines)
    assert any(line.startswith("|") and line.endswith("|") for line in lines)
    assert "amount due" in result.stdout


def test_search_image_match_has_no_page_line(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _seed_indexed_image(db_path, "/docs/scan.png", "Signed by John Doe")

    result = runner.invoke(app, ["search", "john doe"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "File: /docs/scan.png" in lines
    assert not any(line.startswith("Page:") for line in lines)


def test_search_shows_all_matches_without_prompting(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    for i in range(15):
        _seed_indexed_pdf(db_path, f"/docs/report-{i:02d}.pdf", "budget overview")

    result = runner.invoke(app, ["search", "budget"])

    assert result.exit_code == 0
    assert "Results: 15 matches" in result.stdout
    assert "Show more?" not in result.stdout
    assert result.stdout.count("File: ") == 15


def test_search_multiple_pages_of_same_file_print_file_once(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    conn = db_module.connect(db_path)
    try:
        source_id = _add_source(conn)
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, file_path, file_type, status) "
            "VALUES (?, '/docs/report.pdf', 'pdf', 'indexed')",
            (source_id,),
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


def test_search_different_files_each_get_their_own_file_line(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    conn = db_module.connect(db_path)
    try:
        source_id = _add_source(conn)
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, file_path, file_type, status) "
            "VALUES (?, '/docs/a.pdf', 'pdf', 'indexed')",
            (source_id,),
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
