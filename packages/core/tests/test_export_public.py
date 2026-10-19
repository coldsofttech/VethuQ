"""Exporting search results and source listings to JSON or HTML."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import vethuq
from tests import fake_pipeline as fp
from vethuq import errors
from vethuq._export import _Exporter, _ExportLanguages, _Page
from vethuq.enums import ExportFormat
from vethuq.search import SearchMatch, SearchResult
from vethuq_addon_api import LanguageSpec

ENGLISH = LanguageSpec(
    "en",
    "English",
    script="latin",
    default=True,
    script_ranges=((0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F)),
)
TELUGU = LanguageSpec(
    "te", "Telugu", native_label="తెలుగు", script="telugu", script_ranges=((0x0C00, 0x0C7F),)
)


def match(**over) -> SearchMatch:
    fields = {
        "file_id": 1,
        "document_id": 1,
        "file_name": "invoice.pdf",
        "file_path": "/docs/invoice.pdf",
        "page_number": 1,
        "total_pages": 1,
        "before": "Total ",
        "matched": "amount due",
        "after": ": $1,200.00",
        "truncated_before": False,
        "truncated_after": False,
        "duplicate_of_path": None,
        "source": "native",
        "score": None,
        "start": 6,
        "end": 16,
        "engine": "like",
        "matched_by": ("like",),
        "modifiers": (),
    }
    fields.update(over)
    return SearchMatch(**fields)


def result(matches=None, **over) -> SearchResult:
    matches = [match()] if matches is None else matches
    fields = {
        "query": "amount due",
        "matches": matches,
        "total": len(matches),
        "engine": "like",
        "levels": {"like": {"unicode": "basic", "case": "ignore"}},
    }
    fields.update(over)
    return SearchResult(**fields)


BADGES = {"like": ("Contains", False), "fuzzy": ("Similar", True), "exact": ("Exact", False)}


@pytest.fixture
def exporter():
    return _Exporter(_ExportLanguages(lambda: [ENGLISH, TELUGU]), lambda: BADGES)


class TestSearchJson:
    def test_it_holds_the_query_how_it_ran_and_the_matches(self, exporter, tmp_path):
        path = exporter.search_results(result(), tmp_path / "out.json", "json")
        payload = json.loads(path.read_text())
        assert payload["query"] == "amount due" and payload["engine"] == "like"
        assert payload["levels"] == {"like": {"unicode": "basic", "case": "ignore"}}
        assert (payload["total"], payload["result_count"]) == (1, 1)
        entry = payload["matches"][0]
        assert entry["file_name"] == "invoice.pdf" and entry["file_path"] == "/docs/invoice.pdf"
        assert (entry["page_number"], entry["total_pages"]) == (1, 1)
        assert entry["matched_text"] == "Total amount due: $1,200.00"
        assert entry["engine"] == "like" and entry["match_type"] == "Contains"
        assert "duplicate_of_path" not in entry and "score" not in entry
        assert "options" not in payload and "pending" not in payload

    def test_truncated_context_gets_ellipses(self, exporter, tmp_path):
        found = match(truncated_before=True, truncated_after=True)
        payload = json.loads(
            exporter.search_results(result([found]), tmp_path / "o.json", "json").read_text()
        )
        assert payload["matches"][0]["matched_text"] == "...Total amount due: $1,200.00..."

    def test_engines_scores_modifiers_and_duplicates_are_recorded(self, exporter, tmp_path):
        found = match(
            engine="fuzzy",
            matched_by=("like", "fuzzy"),
            score=0.83,
            modifiers=("accents",),
            duplicate_of_path="/docs/first.pdf",
        )
        entry = json.loads(
            exporter.search_results(result([found]), tmp_path / "o.json", "json").read_text()
        )["matches"][0]
        assert entry["score"] == 0.83 and entry["match_type"] == "Similar 83%"
        assert entry["matched_by"] == ["like", "fuzzy"] and entry["modifiers"] == ["accents"]
        assert entry["duplicate_of_path"] == "/docs/first.pdf"

    def test_options_and_pages_not_prepared_are_recorded(self, exporter, tmp_path):
        found = result(options={"fuzzy": {"threshold": "loose"}}, pending={"semantic": 12})
        payload = json.loads(
            exporter.search_results(found, tmp_path / "o.json", "json").read_text()
        )
        assert payload["options"] == {"fuzzy": {"threshold": "loose"}}
        assert payload["pending"] == {"semantic": 12}

    def test_a_page_of_the_result_says_how_many_there_are_in_all(self, exporter, tmp_path):
        found = result([match()], total=40)
        payload = json.loads(
            exporter.search_results(found, tmp_path / "o.json", "json").read_text()
        )
        assert (payload["total"], payload["result_count"]) == (40, 1)

    def test_languages_are_found_by_script(self, exporter, tmp_path):
        found = result([match(matched="అమ్మ", before="", after="")], query="అమ్మ")
        payload = json.loads(
            exporter.search_results(found, tmp_path / "o.json", "json").read_text()
        )
        assert payload["query_languages"] == ["te"] and payload["languages"] == ["te"]
        assert payload["matches"][0]["languages"] == ["te"]
        assert "అమ్మ" in (tmp_path / "o.json").read_text()  # written as is, never అ

    def test_generated_at_is_not_iso(self, exporter, tmp_path):
        payload = json.loads(
            exporter.search_results(result(), tmp_path / "o.json", "json").read_text()
        )
        assert not re.match(r"^\d{4}-\d{2}-\d{2}T", payload["generated_at"])


class TestSearchHtml:
    def page(self, exporter, tmp_path, found=None):
        path = exporter.search_results(found or result(), tmp_path / "o.html", "html")
        return path.read_text(encoding="utf-8")

    def test_it_links_the_file_and_highlights_the_match(self, exporter, tmp_path):
        text = self.page(exporter, tmp_path)
        assert Path("/docs/invoice.pdf").resolve().as_uri() in text
        assert "<mark>amount due</mark>" in text and "<details" in text
        assert "<span>1</span>\n    <span>1</span>" in text

    def test_text_is_escaped(self, exporter, tmp_path):
        found = result([match(before="<b>", matched="due", after="</b> & more")], query="<due>")
        text = self.page(exporter, tmp_path, found)
        assert "&lt;b&gt;<mark>due</mark>&lt;/b&gt; &amp; more" in text
        assert "<due>" not in text

    def test_a_missing_page_number_is_a_dash(self, exporter, tmp_path):
        text = self.page(exporter, tmp_path, result([match(page_number=None, total_pages=None)]))
        assert "<span>-</span>\n    <span>-</span>" in text

    def test_branding_summary_logo_and_print(self, exporter, tmp_path):
        text = self.page(exporter, tmp_path, result([match(), match(page_number=2)]))
        assert "Generated by VethuQ" in text
        assert "Document intelligence and evidence infrastructure." in text
        assert '<svg class="logo"' in text and text.count('id="m"') == 1
        assert 'rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,' in text
        assert 'name="viewport"' in text and "@media print" in text
        assert '<div class="label">Matches</div><div class="value">2</div>' in text
        assert '<div class="label">Files</div><div class="value">1</div>' in text

    def test_nothing_is_left_unfilled_and_the_palette_serves_light_and_dark(
        self, exporter, tmp_path
    ):
        text = self.page(exporter, tmp_path)
        assert "{{" not in text and "<style>" in text and "font-family" in text
        assert "--vq-primary: #005FB8;" in text
        assert "@media (prefers-color-scheme: dark)" in text
        assert 'name="color-scheme" content="light dark"' in text

    def test_how_it_was_found_is_a_pill(self, exporter, tmp_path):
        fuzzy = match(engine="fuzzy", score=0.83, matched_by=("fuzzy",))
        text = self.page(exporter, tmp_path, result([fuzzy, match()], engine="all"))
        assert text.count('<span class="pill">') == 2
        assert "Similar 83%" in text and "Contains" in text

    def test_an_engine_without_a_badge_shows_no_pill(self, tmp_path):
        bare = _Exporter(_ExportLanguages(lambda: [ENGLISH]), lambda: {})
        text = bare.search_results(result(), tmp_path / "o.html", "html").read_text("utf-8")
        assert '<span class="pill">' not in text

    def test_a_badge_falls_back_to_whatever_the_host_gives(self, tmp_path):
        labelled = _Exporter(
            _ExportLanguages(lambda: [ENGLISH]), lambda: {"like": ("Contains (like)", False)}
        )
        text = labelled.search_results(result(), tmp_path / "o.html", "html").read_text("utf-8")
        assert "Contains (like)" in text

    def test_the_settings_are_chips(self, exporter, tmp_path):
        found = result(
            options={"like": {"depth": "2"}},
            pending={"semantic": 3},
            total=10,
        )
        text = self.page(exporter, tmp_path, found)
        assert '<span class="k">Engine</span>like' in text
        assert "unicode=basic, case=ignore" in text and "like depth" in text
        assert "semantic: 3 pages" in text
        assert '<div class="label">Of all matches</div><div class="value">10</div>' in text

    def test_telugu_runs_are_tagged_in_an_english_page(self, exporter, tmp_path):
        found = result([match(before="Name: ", matched="అమ్మ", after=" here")], query="అమ్మ")
        text = self.page(exporter, tmp_path, found)
        assert 'lang="te"' in text
        assert '<span lang="te"><mark>అమ్మ</mark></span>' in text  # the highlight is inside the run
        assert "Telugu" in text  # the languages chip
        assert '<html lang="en">' in text  # English and Telugu: the default, the rest tagged

    def test_a_page_in_one_language_says_so(self, exporter, tmp_path):
        found = result([match(before="", matched="అమ్మ", after="")], query="అమ్మ")
        assert '<html lang="te">' in self.page(exporter, tmp_path, found)

    def test_a_mixed_page_is_in_the_default_language(self, exporter, tmp_path):
        found = result([match(before="Name అమ్మ ", matched="due", after="")], query="due")
        assert '<html lang="en">' in self.page(exporter, tmp_path, found)

    def test_english_text_is_not_tagged(self, exporter, tmp_path):
        assert 'lang="en"><' not in self.page(exporter, tmp_path).replace('<html lang="en">', "")


class TestTemplates:
    @pytest.mark.parametrize(
        "name",
        [
            "export.html",
            "export_row.html",
            "export.css",
            "export.js",
            "list_export.html",
            "section.html",
            "sections_export.html",
            "logo.svg",
            "page_head.html",
            "page_header.html",
            "page_footer.html",
        ],
    )
    def test_template_files_ship_with_the_package(self, name):
        assert _Page.template(name).strip()

    def test_the_page_never_hardcodes_a_color_outside_the_logo(self):
        for name in ("page_head.html", "page_header.html", "page_footer.html", "export.js"):
            assert re.findall(r"#[0-9a-fA-F]{6}\b", _Page.template(name)) == []
        assert re.findall(r"#[0-9a-fA-F]{3,6}\b", _Page.template("export.css")) == []


class TestLanguages:
    languages = _ExportLanguages(lambda: [ENGLISH, TELUGU])

    def test_text_is_recognised_by_script(self):
        assert self.languages.in_text("Museum") == ["en"]
        assert self.languages.in_text("అమ్మ") == ["te"]
        assert self.languages.in_text("Museum అమ్మ") == ["en", "te"]
        assert self.languages.in_text("123 -- ,.") == []

    def test_the_document_language(self):
        assert self.languages.document(["te"]) == "te"
        assert self.languages.document(["en", "te"]) == "en"
        assert self.languages.document([]) == "en"

    def test_names_and_order(self):
        assert self.languages.ordered(["te", "en", "te"]) == ["en", "te"]
        assert self.languages.names(["en", "te", "zz"]) == "English, Telugu, zz"

    def test_a_language_without_ranges_is_never_recognised_or_tagged(self):
        none = _ExportLanguages(lambda: [LanguageSpec("en", "English", default=True)])
        assert none.in_text("Museum") == [] and none.tag("Museum") == "Museum"
        assert none.document([]) == "en"

    def test_no_languages_at_all(self):
        empty = _ExportLanguages(lambda: [])
        assert empty.default() is None and empty.document([]) == "en" and empty.tag("x") == "x"

    def test_runs_stay_together_across_joiners_and_spaces(self):
        tagged = self.languages.tag("a అమ్మ ‌ఇల్లు b")
        assert tagged.count('<span lang="te">') == 1 and tagged.endswith(" b")

    def test_a_trailing_space_stays_outside_the_tag(self):
        assert self.languages.tag("అమ్మ ") == '<span lang="te">అమ్మ</span> '


class TestFormats:
    def test_only_json_and_html(self, exporter, tmp_path):
        with pytest.raises(ValueError, match="json, html"):
            exporter.search_results(result(), tmp_path / "o.xml", "xml")

    def test_a_folder_is_not_a_file(self, exporter, tmp_path):
        with pytest.raises(IsADirectoryError):
            exporter.search_results(result(), tmp_path, "json")

    def test_the_folder_is_created(self, exporter, tmp_path):
        path = exporter.search_results(result(), tmp_path / "a" / "b" / "o.json", "json")
        assert path.is_file() and path.parent.name == "b"


# ----- through the client, with real files ----------------------------------------------------


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def indexed(client, tmp_path):
    root = tmp_path / "docs"
    (root / "sub").mkdir(parents=True)
    pages = {
        "museum.pdf": ["Visit the Museum today. Museums are open.", "Nothing"],
        "sub/cafe.pdf": ["A café near the CAFE sign"],
    }
    for name, texts in pages.items():
        (root / name).write_text(fp.pdf_document(*(fp.native_page(t) for t in texts)))
    (root / "notes.xyz").write_text("not readable")
    client.sources.create(root, languages=["en"])
    assert client.index.run().status.value == "completed"
    return client


class TestClientSearchExport:
    def test_a_result_is_exported_in_the_saved_format(self, indexed, tmp_path):
        result_ = indexed.search.run("museum", engine="like")
        path = indexed.search.export(result_, tmp_path / "out" / "r.json")
        payload = json.loads(path.read_text())
        assert path == tmp_path / "out" / "r.json" and payload["result_count"] == result_.total
        assert payload["query"] == "museum" and payload["engine"] == "like"
        assert all(m["match_type"] == "Contains" for m in payload["matches"])

    def test_html_by_name_or_enum(self, indexed, tmp_path):
        result_ = indexed.search.run("museum", engine="like")
        a = indexed.search.export(result_, tmp_path / "a.html", "html")
        b = indexed.search.export(result_, tmp_path / "b.html", ExportFormat.HTML)
        assert "<mark>Museum</mark>" in a.read_text(encoding="utf-8")
        assert "<!doctype html>" in b.read_text(encoding="utf-8")

    def test_the_default_format_is_a_setting(self, indexed, tmp_path):
        result_ = indexed.search.run("museum", engine="like")
        assert indexed.settings.search.get_export_format() == "json"
        indexed.settings.search.set_export_format("HTML")
        assert indexed.settings.search.get_export_format() == "html"
        text = indexed.search.export(result_, tmp_path / "o.out").read_text(encoding="utf-8")
        assert text.startswith("<!doctype html>")
        indexed.settings.search.reset_export_format()
        assert indexed.settings.search.get_export_format() == "json"
        assert indexed.search.export(result_, tmp_path / "o2.out").read_text().startswith("{")

    def test_a_bad_format_setting_is_refused(self, indexed):
        with pytest.raises(errors.InvalidSettingValueError, match="json, html"):
            indexed.settings.search.set_export_format("pdf")

    def test_a_bad_format_argument_is_refused(self, indexed, tmp_path):
        result_ = indexed.search.run("museum", engine="like")
        with pytest.raises(ValueError, match="json, html"):
            indexed.search.export(result_, tmp_path / "o.pdf", "pdf")

    def test_it_takes_the_result_run_returned(self, indexed, tmp_path):
        with pytest.raises(TypeError, match="SearchResult"):
            indexed.search.export([], tmp_path / "o.json")

    def test_how_each_engine_found_a_match_is_named(self, indexed, tmp_path):
        result_ = indexed.search.run("museum", options="fuzzy.threshold=loose")
        payload = json.loads(indexed.search.export(result_, tmp_path / "o.json").read_text())
        kinds = {m["match_type"] for m in payload["matches"]}
        assert {"Exact", "Contains"} & kinds
        assert any(k.startswith("Similar ") and k.endswith("%") for k in kinds | {"Similar 100%"})
        assert payload["options"] == {"fuzzy": {"threshold": "loose"}}

    def test_the_html_of_a_real_search(self, indexed, tmp_path):
        result_ = indexed.search.run("café", engine="like", normalize="unicode=full")
        text = indexed.search.export(result_, tmp_path / "o.html", "html").read_text("utf-8")
        assert "{{" not in text and "cafe.pdf" in text and '<html lang="en">' in text
        assert "unicode=full, case=ignore" in text

    def test_an_empty_result_exports(self, indexed, tmp_path):
        result_ = indexed.search.run("zzzzzz", engine="like")
        assert (
            json.loads(indexed.search.export(result_, tmp_path / "o.json").read_text())["matches"]
            == []
        )
        text = indexed.search.export(result_, tmp_path / "o.html", "html").read_text("utf-8")
        assert '<div class="value">0</div>' in text


class TestClientSourceExport:
    def test_sources_as_json(self, indexed, tmp_path):
        path = indexed.sources.export(indexed.sources.list(), tmp_path / "s.json")
        payload = json.loads(path.read_text())
        assert payload["source_count"] == 1
        assert payload["sources"][0]["type"] == "folder" and payload["sources"][0]["languages"] == [
            "en"
        ]

    def test_sources_as_html(self, indexed, tmp_path):
        text = indexed.sources.export(
            indexed.sources.list(), tmp_path / "s.html", "html"
        ).read_text("utf-8")
        assert "{{" not in text and "<table" in text and "Sources" in text
        assert '<span class="pill ok">completed</span>' in text
        assert '<div class="label">Folders</div><div class="value">1</div>' in text
        assert "docs" in text

    def test_sources_default_to_every_active_source(self, indexed, tmp_path):
        path = indexed.sources.export(output=tmp_path / "s.json")
        assert json.loads(path.read_text())["source_count"] == 1

    def test_include_removed(self, indexed, tmp_path):
        source = indexed.sources.list()[0]
        indexed.sources.remove(source.id)
        active = indexed.sources.export(output=tmp_path / "a.json")
        everything = indexed.sources.export(output=tmp_path / "b.json", include_removed=True)
        assert json.loads(active.read_text())["source_count"] == 0
        assert json.loads(everything.read_text())["source_count"] == 1

    def test_extension_is_added_when_missing(self, indexed, tmp_path):
        sources = indexed.sources.list()
        assert indexed.sources.export(sources, tmp_path / "export", "html").name == "export.html"
        assert indexed.sources.export(sources, tmp_path / "other").name == "other.json"
        assert indexed.sources.export(sources, tmp_path / "keep.txt", "html").name == "keep.txt"

    def test_files_without_detail(self, indexed, tmp_path):
        source = indexed.sources.list()[0]
        files = indexed.sources.list_files(source.id)
        payload = json.loads(
            indexed.sources.export_files(source, files, tmp_path / "f.json").read_text()
        )
        assert payload["detail"] is False and payload["file_count"] == len(files)
        assert {f["relative_path"] for f in payload["files"]} >= {"museum.pdf", "sub/cafe.pdf"}
        text = indexed.sources.export_files(
            source.id, files, tmp_path / "f.html", "html"
        ).read_text("utf-8")
        assert "Confidence" not in text and "museum.pdf" in text and "sub/cafe.pdf" in text

    def test_files_with_detail(self, indexed, tmp_path):
        source = indexed.sources.list()[0]
        files = indexed.sources.list_files(source.id, detailed=True)
        payload = json.loads(
            indexed.sources.export_files(source, files, tmp_path / "f.json").read_text()
        )
        assert payload["detail"] is True
        by_name = {f["relative_path"]: f for f in payload["files"]}
        assert by_name["museum.pdf"]["index"]["status"] == "indexed"
        assert by_name["museum.pdf"]["index"]["pages"] == 2
        text = indexed.sources.export_files(source, files, tmp_path / "f.html", "html").read_text(
            "utf-8"
        )
        assert '<span class="pill ok">indexed</span>' in text
        assert '<span class="pill muted">unsupported</span>' in text
        for header in ("Status", "Confidence", "Band", "Languages", "Duplicate Of", "Error"):
            assert f"<th>{header}</th>" in text
        assert '<div class="label">Indexed</div><div class="value">2</div>' in text

    def test_a_source_by_path_and_an_unknown_one(self, indexed, tmp_path):
        source = indexed.sources.list()[0]
        files = indexed.sources.list_files(source.path)
        assert indexed.sources.export_files(source.path, files, tmp_path / "f.json").is_file()
        with pytest.raises(errors.SourceNotFoundError):
            indexed.sources.export_files(999, files, tmp_path / "x.json")

    def test_the_default_format_applies(self, indexed, tmp_path):
        indexed.settings.search.set_export_format("html")
        text = indexed.sources.export(indexed.sources.list(), tmp_path / "s.out").read_text("utf-8")
        assert text.startswith("<!doctype html>")

    def test_a_bad_format_and_a_folder(self, indexed, tmp_path):
        with pytest.raises(ValueError, match="json, html"):
            indexed.sources.export([], tmp_path / "s.csv", "csv")
        with pytest.raises(IsADirectoryError):
            indexed.sources.export([], tmp_path)

    def test_paths_with_markup_are_escaped(self, tmp_path):
        from vethuq.enums import SourceStatus, SourceType
        from vethuq.sources import Source

        source = Source(
            path="/docs/<script>alert(1)</script>",
            id=1,
            source_type=SourceType.FOLDER,
            status=SourceStatus.COMPLETED,
            added_at="2026-01-01",
        )
        exporter = _Exporter(_ExportLanguages(lambda: [ENGLISH]), lambda: {})
        text = exporter.sources([source], tmp_path / "s.html", "html").read_text("utf-8")
        assert "<script>alert" not in text and "&lt;script&gt;" in text
