"""What a file type keeps about a page beside its text, in a table of its own."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from vethuq._db.models import (
    _Base,
    _CssPage,
    _CsvPage,
    _DocPage,
    _DocxPage,
    _EmlPage,
    _HtmlPage,
    _JsonPage,
    _JsPage,
    _MarkdownPage,
    _NdjsonPage,
    _ParquetPage,
    _PptPage,
    _PptxPage,
    _RtfPage,
    _TsvPage,
    _TxtPage,
    _XlsPage,
    _XlsxPage,
    _XmlPage,
    _YamlPage,
)


class _PageDetails:
    """The text of every page is in `pdf_pages`. A file type that has more to say about a page
    (`ReadPage.details`) has a table of its own, one row per page, with a column per fact. A type
    without a table, and a fact without a column, are ignored."""

    TABLES: dict[str, type[_Base]] = {
        "txt": _TxtPage,
        "csv": _CsvPage,
        "tsv": _TsvPage,
        "markdown": _MarkdownPage,
        "html": _HtmlPage,
        "xml": _XmlPage,
        "css": _CssPage,
        "js": _JsPage,
        "json": _JsonPage,
        "yaml": _YamlPage,
        "parquet": _ParquetPage,
        "ndjson": _NdjsonPage,
        "docx": _DocxPage,
        "doc": _DocPage,
        "xlsx": _XlsxPage,
        "xls": _XlsPage,
        "pptx": _PptxPage,
        "ppt": _PptPage,
        "rtf": _RtfPage,
        "eml": _EmlPage,
    }

    @staticmethod
    def clear(session: Session, page_id: int) -> None:
        """Forget what every file type kept about a page (it is being read again)."""
        for table in _PageDetails.TABLES.values():
            row = session.get(table, page_id)
            if row is not None:
                session.delete(row)

    @staticmethod
    def save(
        session: Session, file_type: str, page_id: int, details: Mapping[str, Any] | None
    ) -> None:
        table = _PageDetails.TABLES.get(file_type)
        if table is None or not details:
            return
        columns = {c.name for c in table.__table__.columns} - {"page_id"}  # type: ignore[attr-defined]
        values = {k: v for k, v in details.items() if k in columns}
        if values and session.get(table, page_id) is None:
            session.add(table(page_id=page_id, **values))
