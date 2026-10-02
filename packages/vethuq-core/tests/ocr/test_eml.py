import sqlite3
from email.message import EmailMessage
from pathlib import Path

import pytest
from vethuq_core.ocr import Quick
from vethuq_core.ocr.reader import EmlReader, Readers
from vethuq_core.search import Search
from vethuq_core.source import Sources


def _write_eml(path: Path, *, body: str = "Quarterly numbers attached.", html: str | None = None):
    message = EmailMessage()
    message["From"] = "Alice Ünal <alice@example.com>"
    message["To"] = "bob@example.com, carol@example.com"
    message["Cc"] = "dave@example.com"
    message["Subject"] = "Budget review Q3 ✓"
    message["Date"] = "Tue, 02 Sep 2025 10:30:00 +0000"
    message["Message-ID"] = "<abc123@example.com>"
    if body:
        message.set_content(body)
    if html is not None:
        if body:
            message.add_alternative(html, subtype="html")
        else:
            message.set_content(html, subtype="html")
    message.add_attachment(
        b"SECRETATTACHMENTTEXT", maintype="application", subtype="octet-stream", filename="a.bin"
    )
    path.write_bytes(message.as_bytes())
    return path


class TestEmlReader:
    def test_eml_suffix_is_registered(self, tmp_path):
        eml = tmp_path / "m.eml"
        assert Readers.is_supported(eml)
        assert Readers.for_path(eml).file_type == "eml"

    def test_reads_headers_and_body_without_attachments(self, tmp_path):
        page = EmlReader.read_file(_write_eml(tmp_path / "m.eml"))

        assert page.source == "native"
        assert page.confidence == 1.0
        assert page.phase_columns() == (1, "")
        assert "Quarterly numbers attached." in page.text
        assert "Subject: Budget review Q3 ✓" in page.text
        assert "alice@example.com" in page.text
        assert "SECRETATTACHMENTTEXT" not in page.text and "a.bin" not in page.text
        assert page.email_headers == {
            "sender": "Alice Ünal <alice@example.com>",
            "recipients_to": "bob@example.com, carol@example.com",
            "recipients_cc": "dave@example.com",
            "recipients_bcc": None,
            "reply_to": None,
            "subject": "Budget review Q3 ✓",
            "message_id": "<abc123@example.com>",
            "sent_at": "2025-09-02T10:30:00+00:00",
        }

    def test_html_only_body_is_converted_to_text(self, tmp_path):
        html = (
            "<html><head><style>p{color:red}</style></head><body>"
            "<script>alert('x')</script><p>Hello <b>there</b></p><div>Second line</div>"
            "</body></html>"
        )
        page = EmlReader.read_file(_write_eml(tmp_path / "h.eml", body="", html=html))

        assert "Hello there" in page.text
        assert "Second line" in page.text
        assert "alert" not in page.text and "color:red" not in page.text

    def test_plain_part_preferred_over_html(self, tmp_path):
        page = EmlReader.read_file(
            _write_eml(tmp_path / "p.eml", body="plain wins", html="<p>html loses</p>")
        )
        assert "plain wins" in page.text and "html loses" not in page.text

    def test_malformed_date_leaves_sent_at_empty(self, tmp_path):
        path = tmp_path / "bad.eml"
        path.write_bytes(b"From: a@b.c\nDate: not a date\nSubject: s\n\nbody\n")
        page = EmlReader.read_file(path)
        assert page.email_headers is not None and page.email_headers["sent_at"] is None
        assert "body" in page.text


class TestEmlIndexing:
    def test_run_indexes_eml_with_header_columns_and_is_searchable(
        self, conn: sqlite3.Connection, tmp_path
    ):
        path = _write_eml(tmp_path / "m.eml")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        doc = conn.execute("SELECT * FROM document_index").fetchone()
        assert (doc["status"], doc["file_type"]) == ("indexed", "eml")
        page = conn.execute(
            "SELECT * FROM eml_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["subject"] == "Budget review Q3 ✓"
        assert page["sender"] == "Alice Ünal <alice@example.com>"
        assert page["sent_at"] == "2025-09-02T10:30:00+00:00"
        assert page["confidence"] == 1.0

        body_hit = Search.indexed_content(conn, "quarterly numbers")
        header_hit = Search.indexed_content(conn, "carol@example.com")
        assert [m.file_name for m in body_hit] == ["m.eml"]
        assert [m.file_name for m in header_hit] == ["m.eml"]
        assert Search.indexed_content(conn, "SECRETATTACHMENTTEXT") == []

        metrics = conn.execute("SELECT * FROM confidence_metrics").fetchone()
        assert (metrics["file_type"], metrics["process_type"]) == ("eml", "native")

    def test_duplicate_eml_reuses_original_pages(self, conn: sqlite3.Connection, tmp_path):
        folder = tmp_path / "mail"
        folder.mkdir()
        _write_eml(folder / "a.eml")
        (folder / "b.eml").write_bytes((folder / "a.eml").read_bytes())
        source = Sources.add(conn, folder)

        Quick.run(conn, source)

        assert conn.execute("SELECT COUNT(*) FROM eml_pages").fetchone()[0] == 1
        assert sorted(m.file_name for m in Search.indexed_content(conn, "quarterly")) == [
            "a.eml",
            "b.eml",
        ]

    def test_purging_removed_source_deletes_eml_pages(self, conn: sqlite3.Connection, tmp_path):
        source = Sources.add(conn, _write_eml(tmp_path / "m.eml"))
        Quick.run(conn, source)
        assert conn.execute("SELECT COUNT(*) FROM eml_pages").fetchone()[0] == 1

        Sources.remove(conn, source.id)
        Sources.purge_expired_sources(conn, retention_minutes=-1)

        assert conn.execute("SELECT COUNT(*) FROM eml_pages").fetchone()[0] == 0
        assert Search.indexed_content(conn, "quarterly") == []


@pytest.mark.parametrize("table", ["document_index", "processing_metrics", "confidence_metrics"])
def test_schema_accepts_eml_file_type(conn: sqlite3.Connection, table):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()["sql"]
    assert "'eml'" in sql
