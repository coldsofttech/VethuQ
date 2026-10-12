"""Filters in the HTML exports, and exporting any listing or several (`client.export`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import vethuq
from tests.test_export_public import exporter, match, result  # noqa: F401 - fixture and helpers
from vethuq._export import _Facets, _Page
from vethuq.export import ExportSection

COLUMNS = [("id", "ID"), ("path", "Path"), ("status", "Status"), ("kind", "Kind")]
RECORDS = [
    {"id": 1, "path": "/docs/a.pdf", "status": "indexed", "kind": "pdf"},
    {"id": 2, "path": "/docs/b.txt", "status": "error", "kind": "txt"},
    {"id": 3, "path": "/docs/c.pdf", "status": "indexed", "kind": None},
]


class TestTemplates:
    def test_every_page_has_a_slot_for_the_filters_and_the_script(self):
        for name in ("export.html", "list_export.html"):
            assert "{{FACETS}}" in _Page.template(name)
        assert "{{FACETS}}" in _Page.template("export_row.html")
        assert "{{SCRIPT}}" in _Page.template("list_export.html")
        assert "{{SCRIPT}}" in _Page.template("sections_export.html")

    def test_the_report_templates_hold_the_slots_the_exporter_fills(self):
        page = _Page.template("sections_export.html")
        for slot in ("{{TITLE}}", "{{CARDS}}", "{{SECTIONS}}", "{{HEAD}}", "{{FOOTER}}"):
            assert slot in page
        assert "{{SECTION_TITLE}}" in _Page.template("section.html")
        assert "data-scope" in _Page.template("section.html")

    def test_the_script_filters_by_facet_and_each_section_on_its_own(self):
        script = _Page.template("export.js")
        for part in ("data-facets", "data-clear", "[data-scope]", "Showing ", "beforeprint"):
            assert part in script
        assert ".filters" in _Page.template("export.css")
        assert "details.facet" in _Page.template("export.css")


class TestFacets:
    def test_a_facet_with_two_values_is_a_dropdown_with_counts_and_rows_carry_their_values(self):
        rows = [{"type": ["PDF"]}, {"type": ["TXT"]}, {"type": ["PDF"]}]
        bar, attrs = _Facets.bar([("type", "File type")], rows)
        assert 'data-facet="type"' in bar and "File type" in bar
        assert bar.index('value="PDF"') < bar.index('value="TXT"')  # the commoner first
        assert '<span class="count">2</span>' in bar
        assert attrs[0] == 'data-facets="{&quot;type&quot;: [&quot;PDF&quot;]}"'
        assert "data-clear" in bar and "facet-status" in bar

    def test_a_facet_that_would_not_split_anything_is_left_out(self):
        bar, attrs = _Facets.bar([("type", "File type")], [{"type": ["PDF"]}, {"type": ["PDF"]}])
        assert bar == "" and len(attrs) == 2

    def test_values_are_escaped_and_can_be_marked_up(self):
        rows = [{"k": ["<b>"]}, {"k": ["x"]}]
        bar, _ = _Facets.bar([("k", "K")], rows, lambda escaped: f"[{escaped}]")
        assert "&lt;b&gt;" in bar and "<b>" not in bar and "[x]" in bar


class TestSearchFilters:
    def test_matches_of_different_kinds_get_a_filter_bar_and_per_row_values(
        self,
        exporter,  # noqa: F811
        tmp_path,
    ):
        found = result(
            [
                match(file_path="/docs/a/invoice.pdf", file_name="invoice.pdf", source="native"),
                match(file_path="/docs/b/scan.png", file_name="scan.png", source="ocr"),
            ]
        )
        text = exporter.search_results(found, tmp_path / "o.html", "html").read_text("utf-8")
        for label in ("File type", "Text from", "Folder"):
            assert label in text
        assert "Match type" not in text  # both found by `like`: nothing to split
        rows = re.findall(r'<details class="row" data-facets="([^"]*)"', text)
        assert len(rows) == 2
        assert "PDF" in rows[0] and "PNG" in rows[1] and "OCR" in rows[1]

    def test_a_single_match_has_nothing_to_filter(self, exporter, tmp_path):  # noqa: F811
        text = exporter.search_results(result(), tmp_path / "o.html", "html").read_text("utf-8")
        assert 'class="filters"' not in text
        assert '<details class="row" data-facets=' in text

    def test_the_engine_filter_uses_the_names_exports_give_engines(self, exporter, tmp_path):  # noqa: F811
        found = result([match(engine="like"), match(engine="exact", file_path="/docs/b.pdf")])
        text = exporter.search_results(found, tmp_path / "o.html", "html").read_text("utf-8")
        assert "Match type" in text and "Contains" in text and "Exact" in text

    def test_the_page_carries_its_script_once(self, exporter, tmp_path):  # noqa: F811
        text = exporter.search_results(result(), tmp_path / "o.html", "html").read_text("utf-8")
        assert text.count("<script>") == 1 and "{{" not in text


class TestRecords:
    def test_json_holds_the_records_as_they_are(self, exporter, tmp_path):  # noqa: F811
        path = exporter.records(
            RECORDS, COLUMNS, tmp_path / "r.json", "json", title="Files", key="files"
        )
        payload = json.loads(path.read_text())
        assert (payload["title"], payload["count"]) == ("Files", 3)
        assert payload["files"] == RECORDS and "generated_at" in payload

    def test_html_shows_pills_links_filters_and_dashes_for_nothing(self, exporter, tmp_path):  # noqa: F811
        path = exporter.records(
            RECORDS,
            COLUMNS,
            tmp_path / "r.html",
            "html",
            title="Files",
            key="files",
            statuses=("status",),
            paths=("path",),
            facets=("status", "kind"),
            cards=[("Errors", "1")],
        )
        text = path.read_text("utf-8")
        assert '<span class="pill ok">indexed</span>' in text
        assert '<span class="pill bad">error</span>' in text
        assert 'href="file:///docs/a.pdf"' in text
        assert "<td>-</td>" in text  # the missing kind
        assert text.count('class="facet"') == 2 and 'data-facet="status"' in text
        assert re.findall(r'<tr data-facets="([^"]*)"', text)[2].count("kind") == 0
        assert "Errors" in text and "{{" not in text

    def test_a_format_function_gives_a_cell_its_html(self, exporter, tmp_path):  # noqa: F811
        path = exporter.records(
            RECORDS,
            COLUMNS,
            tmp_path / "r.html",
            "html",
            title="Files",
            key="files",
            formats={"id": lambda value: f"<b>#{value}</b>"},
        )
        assert "<b>#2</b>" in path.read_text("utf-8")

    def test_text_in_a_record_is_escaped(self, exporter, tmp_path):  # noqa: F811
        path = exporter.records(
            [{"id": "<script>alert(1)</script>"}],
            [("id", "ID")],
            tmp_path / "r.html",
            "html",
            title="T",
            key="t",
        )
        text = path.read_text("utf-8")
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
        assert "<script>alert" not in text


class TestSections:
    def sections(self):
        return [
            ExportSection(
                "Files",
                "files",
                COLUMNS,
                RECORDS,
                statuses=("status",),
                paths=("path",),
                facets=("status",),
            ),
            ExportSection("Failures", "failures", [("reason", "Reason")], [], empty="None."),
        ]

    def test_json_has_each_sections_records_and_the_counts(self, exporter, tmp_path):  # noqa: F811
        path = exporter.sections(self.sections(), tmp_path / "s.json", "json", title="Report")
        payload = json.loads(path.read_text())
        assert payload["counts"] == {"files": 3, "failures": 0}
        assert payload["files"] == RECORDS and payload["failures"] == []

    def test_html_has_a_card_a_heading_and_filters_per_section(self, exporter, tmp_path):  # noqa: F811
        path = exporter.sections(
            self.sections(), tmp_path / "s.html", "html", title="Report", cards=[("Pages", "9")]
        )
        text = path.read_text("utf-8")
        assert text.count('<section class="list-section" data-scope>') == 2
        assert "<h2>Files</h2>" in text and "<h2>Failures</h2>" in text
        assert '<p class="empty">None.</p>' in text and "<table" in text
        assert 'data-facet="status"' in text and "Pages" in text
        assert "{{" not in text and text.count("<script>") == 1


class TestClient:
    @pytest.fixture
    def client(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "v.db")
        yield client
        client.close()

    def test_records_use_the_saved_format_unless_one_is_named(self, client, tmp_path):
        columns = [("id", "ID")]
        path = client.export.records([{"id": 1}], columns, tmp_path / "a", title="T", key="t")
        assert json.loads(path.read_text())["t"] == [{"id": 1}]
        html_path = client.export.records(
            [{"id": 1}], columns, tmp_path / "b.html", "html", title="T", key="t"
        )
        assert html_path.read_text("utf-8").startswith("<!doctype html>")

    def test_a_bad_format_a_bad_facet_and_a_folder_are_refused(self, client, tmp_path):
        columns = [("id", "ID")]
        with pytest.raises(ValueError, match="format must be"):
            client.export.records([], columns, tmp_path / "a", "pdf", title="T", key="t")
        with pytest.raises(ValueError, match="facets must be columns: nope"):
            client.export.records(
                [], columns, tmp_path / "a", "json", title="T", key="t", facets=("nope",)
            )
        with pytest.raises(IsADirectoryError):
            client.export.records([], columns, Path(tmp_path), "json", title="T", key="t")

    def test_sections_check_their_facets_too(self, client, tmp_path):
        bad = ExportSection("S", "s", [("id", "ID")], [], facets=("nope",))
        with pytest.raises(ValueError, match="S: facets must be columns"):
            client.export.sections([bad], tmp_path / "a", "json", title="T")

    def test_the_namespace_is_part_of_the_public_api(self):
        assert "export" in vethuq.__all__ and vethuq.export.ExportSection is ExportSection
