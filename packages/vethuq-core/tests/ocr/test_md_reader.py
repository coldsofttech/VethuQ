import sqlite3
from unittest.mock import patch

import pytest
from vethuq_core.ocr import MdReader, PageResult, Quick, Readers
from vethuq_core.search import Search
from vethuq_core.source import Sources

DOC = """---
title: Budget Review
tags: [finance, q3]
---

# Quarterly **budget** review

Total is [1200 dollars](https://example.com/secret-target) due _soon_.<br>
<div>raw html</div>

| Item | Cost |
| ---- | ---- |
| Rent | 900  |

```python
print("ledger")
```

![chart caption](img/chart.png)
"""


class TestMdReaderExtract:
    def test_strips_markup_and_keeps_content(self):
        text, images = MdReader.extract(DOC)

        assert "Quarterly budget review" in text
        assert "Total is 1200 dollars due soon." in text
        assert "Rent" in text and "900" in text
        assert 'print("ledger")' in text
        assert "chart caption" in text
        for noise in ("**", "](", "secret-target", "```", "<div>", "raw html", "|"):
            assert noise not in text
        assert images == ["img/chart.png"]

    def test_front_matter_values_are_indexed(self):
        text, _ = MdReader.extract(DOC)

        assert "title: Budget Review" in text
        assert "tags: finance, q3" in text

    def test_malformed_front_matter_is_ignored(self):
        text, _ = MdReader.extract("---\nkey: [unclosed\n---\n\nbody text\n")

        assert text == "body text"

    def test_empty_document(self):
        assert MdReader.extract("") == ("", [])


class TestMdReaderResolveImage:
    @pytest.fixture
    def md(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "a b.png").write_bytes(b"x")
        (tmp_path / "doc.txt").write_text("not an image")
        return tmp_path / "note.md"

    def test_relative_and_percent_encoded_paths(self, md):
        assert MdReader.resolve_image(md, "img/a%20b.png") == md.parent / "img" / "a b.png"
        assert MdReader.resolve_image(md, "img/a%20b.png?raw=1#x") is not None

    def test_absolute_path(self, md):
        target = md.parent / "img" / "a b.png"
        assert MdReader.resolve_image(md, str(target)) == target

    @pytest.mark.parametrize(
        "target",
        [
            "",
            "https://example.com/a.png",
            "//cdn.example.com/a.png",
            "data:image/png;base64,AAAA",
            "file:///etc/a.png",
            "img/missing.png",
            "doc.txt",
        ],
    )
    def test_non_local_or_unusable_targets_are_ignored(self, md, target):
        assert MdReader.resolve_image(md, target) is None


class TestMdReaderFile:
    def test_plain_markdown_is_native_without_engine(self, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("# Title\n\nHello *world*", encoding="utf-8")

        with patch("vethuq_core.ocr.Engine.get") as get_engine:
            page = MdReader().ocr(None, path)[0]  # type: ignore[arg-type]

        get_engine.assert_not_called()
        assert page.text == "Title\nHello world"
        assert (page.source, page.confidence, page.encoding) == ("native", 1.0, "utf-8")
        assert page.ocr_engine is None

    def test_local_image_text_is_appended_and_marks_page_mixed(self, tmp_path):
        (tmp_path / "pic.png").write_bytes(b"x")
        path = tmp_path / "n.md"
        path.write_text("intro\n\n![alt](pic.png)\n![again](pic.png)\n![r](https://x/y.png)")

        image = PageResult(text="INVOICE 42", confidence=0.8, source="ocr")
        with patch("vethuq_core.ocr.reader.ImageReader.ocr_file", return_value=image) as ocr:
            page = MdReader.read_file(None, path)  # type: ignore[arg-type]

        assert ocr.call_count == 1  # duplicate and remote references are skipped
        assert "intro" in page.text and page.text.endswith("INVOICE 42")
        assert page.source == "mixed"
        assert page.confidence == pytest.approx(0.9)
        assert page.ocr_engine is not None

    def test_failing_image_ocr_does_not_fail_the_file(self, tmp_path):
        (tmp_path / "pic.png").write_bytes(b"x")
        path = tmp_path / "n.md"
        path.write_text("body ![a](pic.png)")

        with patch("vethuq_core.ocr.reader.ImageReader.ocr_file", side_effect=RuntimeError):
            page = MdReader.read_file(None, path)  # type: ignore[arg-type]

        assert page.source == "native"
        assert "body" in page.text

    def test_registered_for_md_and_markdown_suffixes(self, tmp_path):
        for name in ("A.MD", "a.markdown"):
            assert Readers.for_path(tmp_path / name).file_type == "md"
        assert Readers.new_file_type_counts()["md"] == 0


class TestMdIndexing:
    @patch("vethuq_core.ocr.Engine.get")
    def test_run_indexes_and_searches_markdown(
        self, mock_get_engine, conn: sqlite3.Connection, tmp_path
    ):
        path = tmp_path / "notes.md"
        path.write_text("# Plan\n\nThe **launch** date is fixed.", encoding="utf-8")
        source = Sources.add(conn, path)

        Quick.run(conn, source)

        mock_get_engine.assert_not_called()
        doc = conn.execute("SELECT * FROM document_index").fetchone()
        assert (doc["status"], doc["file_type"]) == ("indexed", "md")
        page = conn.execute(
            "SELECT * FROM text_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["source"] == "native"

        confidence = conn.execute(
            "SELECT page_count FROM confidence_metrics "
            "WHERE file_type = 'md' AND process_type = 'native'"
        ).fetchone()
        assert confidence["page_count"] == 1

        matches = Search.indexed_content(conn, "launch DATE")
        assert [(m.file_name, m.page_number) for m in matches] == [("notes.md", None)]
        assert Search.indexed_content(conn, "**") == []

    def test_removing_source_deletes_text_pages(self, conn: sqlite3.Connection, tmp_path):
        path = tmp_path / "notes.md"
        path.write_text("some searchable words", encoding="utf-8")
        source = Sources.add(conn, path)
        Quick.run(conn, source)

        Sources.remove(conn, source.id)
        Sources.purge_expired_sources(conn, retention_minutes=0)

        assert conn.execute("SELECT COUNT(*) FROM text_pages").fetchone()[0] == 0
