"""The per-type tables of the licensed file types (web, developer and office)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import tests.fake_pipeline as fp
import vethuq
from vethuq._db import (
    _CsPage,
    _CssPage,
    _DocPage,
    _DocxPage,
    _DotPage,
    _DotxPage,
    _EmlPage,
    _GoPage,
    _HtmlPage,
    _IniPage,
    _IpynbPage,
    _JavaPage,
    _JsonPage,
    _JsPage,
    _JsxPage,
    _LogPage,
    _MhtmlPage,
    _MsgPage,
    _NdjsonPage,
    _OdpPage,
    _OdsPage,
    _OdtPage,
    _OtpPage,
    _OtsPage,
    _OttPage,
    _ParquetPage,
    _PdfPage,
    _PhpPage,
    _PpsPage,
    _PpsxPage,
    _PptmPage,
    _PptPage,
    _PptxPage,
    _Ps1Page,
    _PyPage,
    _RbPage,
    _RsPage,
    _RssPage,
    _RstPage,
    _RtfPage,
    _ShPage,
    _SqlPage,
    _SvgPage,
    _TomlPage,
    _TsPage,
    _TsvPage,
    _TsxPage,
    _XlsbPage,
    _XlsmPage,
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
    (
        "svg",
        _SvgPage,
        {
            "encoding": "utf-8",
            "width": "200",
            "height": "100",
            "view_box": "0 0 200 100",
            "text_count": 3,
            "image_count": 1,
            "well_formed": True,
        },
    ),
    ("py", _PyPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("java", _JavaPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("ts", _TsPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("tsx", _TsxPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("jsx", _JsxPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("cs", _CsPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("go", _GoPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("rs", _RsPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("php", _PhpPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("rb", _RbPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("sh", _ShPage, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    ("ps1", _Ps1Page, {"encoding": "utf-8", "line_count": 120, "comment_lines": 14}),
    (
        "ipynb",
        _IpynbPage,
        {
            "encoding": "utf-8",
            "nbformat": 4,
            "language": "python",
            "cell_count": 12,
            "code_cells": 7,
            "markdown_cells": 5,
        },
    ),
    ("ini", _IniPage, {"encoding": "utf-8", "section_count": 3, "key_count": 14}),
    ("sql", _SqlPage, {"encoding": "utf-8", "statement_count": 5, "line_count": 40}),
    (
        "rst",
        _RstPage,
        {"encoding": "utf-8", "title": "Guide", "section_count": 4, "line_count": 120},
    ),
    (
        "log",
        _LogPage,
        {
            "encoding": "utf-8",
            "line_count": 900,
            "error_count": 3,
            "warning_count": 12,
            "truncated": False,
        },
    ),
    (
        "toml",
        _TomlPage,
        {"encoding": "utf-8", "value_count": 9, "table_count": 3, "max_depth": 3},
    ),
    ("tsv", _TsvPage, {"encoding": "utf-8", "row_count": 4, "column_count": 3}),
    ("css", _CssPage, {"encoding": "utf-8", "rule_count": 3, "image_count": 1}),
    ("js", _JsPage, {"encoding": "utf-8", "line_count": 40, "comment_lines": 6}),
    ("json", _JsonPage, {"encoding": "utf-8", "kind": "object", "value_count": 9, "max_depth": 3}),
    (
        "yaml",
        _YamlPage,
        {"encoding": "utf-8", "document_count": 2, "value_count": 9, "max_depth": 3},
    ),
    (
        "mhtml",
        _MhtmlPage,
        {
            "encoding": "utf-8",
            "title": "Harvest",
            "url": "https://example.com/news",
            "lang": "en",
            "link_count": 4,
            "image_count": 2,
            "frame_count": 1,
        },
    ),
    (
        "ndjson",
        _NdjsonPage,
        {
            "encoding": "utf-8",
            "record_count": 40,
            "invalid_line_count": 2,
            "value_count": 120,
            "max_depth": 3,
            "truncated": False,
        },
    ),
    (
        "parquet",
        _ParquetPage,
        {"row_count": 1000, "column_count": 4, "row_group_count": 2, "indexed_row_count": 990},
    ),
    ("dot", _DotPage, {"line_count": 12, "image_count": 2}),
    ("dotx", _DotxPage, {"line_count": 12, "image_count": 2}),
    ("xlsm", _XlsmPage, {"line_count": 12, "image_count": 2}),
    ("xlsb", _XlsbPage, {"line_count": 12, "image_count": 2}),
    ("pptm", _PptmPage, {"line_count": 12, "image_count": 2}),
    ("pps", _PpsPage, {"line_count": 12, "image_count": 2}),
    ("ppsx", _PpsxPage, {"line_count": 12, "image_count": 2}),
    ("odt", _OdtPage, {"line_count": 12, "image_count": 2}),
    ("ott", _OttPage, {"line_count": 12, "image_count": 2}),
    ("ods", _OdsPage, {"line_count": 12, "image_count": 2}),
    ("ots", _OtsPage, {"line_count": 12, "image_count": 2}),
    ("odp", _OdpPage, {"line_count": 12, "image_count": 2}),
    ("otp", _OtpPage, {"line_count": 12, "image_count": 2}),
    ("docx", _DocxPage, {"line_count": 12, "image_count": 2}),
    ("doc", _DocPage, {"line_count": 12, "image_count": 2}),
    ("xlsx", _XlsxPage, {"line_count": 12, "image_count": 2}),
    ("xls", _XlsPage, {"line_count": 12, "image_count": 2}),
    ("pptx", _PptxPage, {"line_count": 12, "image_count": 2}),
    ("ppt", _PptPage, {"line_count": 12, "image_count": 2}),
    (
        "rss",
        _RssPage,
        {
            "encoding": "utf-8",
            "feed_format": "atom",
            "title": "Dev Blog",
            "language": "en",
            "item_count": 12,
            "updated": "2026-10-14T10:00:00Z",
            "well_formed": True,
        },
    ),
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
    (
        "msg",
        _MsgPage,
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
