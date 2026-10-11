"""The per-type tables of the licensed file types (web, developer and office)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import tests.fake_pipeline as fp
import vethuq
from vethuq._db import (
    _CssPage,
    _DocPage,
    _DocxPage,
    _EmlPage,
    _HtmlPage,
    _JsonPage,
    _JsPage,
    _PdfPage,
    _PptPage,
    _PptxPage,
    _RtfPage,
    _XlsPage,
    _XlsxPage,
    _XmlPage,
    _YamlPage,
)
from vethuq._filetypes import _PageDetails

CASES = [
    (
        "html",
        _HtmlPage,
        {"encoding": "utf-8", "title": "T", "lang": "en", "link_count": 2, "image_count": 1},
    ),
    (
        "xml",
        _XmlPage,
        {
            "encoding": "utf-8",
            "root": "catalog",
            "element_count": 5,
            "attribute_count": 2,
            "well_formed": True,
        },
    ),
    ("css", _CssPage, {"encoding": "utf-8", "rule_count": 3, "image_count": 1}),
    ("js", _JsPage, {"encoding": "utf-8", "line_count": 40, "comment_lines": 6}),
    ("json", _JsonPage, {"encoding": "utf-8", "kind": "object", "value_count": 9, "max_depth": 3}),
    (
        "yaml",
        _YamlPage,
        {"encoding": "utf-8", "document_count": 2, "value_count": 9, "max_depth": 3},
    ),
    ("docx", _DocxPage, {"line_count": 12, "image_count": 2}),
    ("doc", _DocPage, {"line_count": 12, "image_count": 2}),
    ("xlsx", _XlsxPage, {"line_count": 12, "image_count": 2}),
    ("xls", _XlsPage, {"line_count": 12, "image_count": 2}),
    ("pptx", _PptxPage, {"line_count": 12, "image_count": 2}),
    ("ppt", _PptPage, {"line_count": 12, "image_count": 2}),
    ("rtf", _RtfPage, {"line_count": 12, "image_count": 2}),
    (
        "eml",
        _EmlPage,
        {
            "subject": "S",
            "sender": "a@b.c",
            "recipients_to": "d@e.f",
            "recipients_cc": None,
            "recipients_bcc": None,
            "reply_to": None,
            "sent_at": "2025-09-02T10:30:00+00:00",
            "message_id": "<m@x>",
        },
    ),
]


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_workers(0)
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.pdf").write_text(fp.pdf_document(fp.native_page()))
        client.sources.create(folder)
        assert client.index.run().status.value == "completed"
        yield client


@pytest.mark.parametrize(("file_type", "table", "details"), CASES)
def test_a_table_keeps_each_fact_of_its_type(client, file_type, table, details):
    with client._db().session() as session:  # noqa: SLF001
        page_id = session.scalar(select(_PdfPage.id))
        _PageDetails.save(session, file_type, page_id, {**details, "unknown_fact": 1})
        session.flush()
        row = session.get(table, page_id)
        assert {name: getattr(row, name) for name in details} == details


@pytest.mark.parametrize(("file_type", "table", "details"), CASES)
def test_reading_a_page_again_forgets_what_was_kept(client, file_type, table, details):
    with client._db().session() as session:  # noqa: SLF001
        page_id = session.scalar(select(_PdfPage.id))
        _PageDetails.save(session, file_type, page_id, details)
        session.flush()
        _PageDetails.clear(session, page_id)
        session.flush()
        assert session.get(table, page_id) is None
