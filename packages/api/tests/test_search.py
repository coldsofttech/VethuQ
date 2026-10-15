from __future__ import annotations

import os
from pathlib import Path

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq.errors import FileTypeUnavailableError
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.search_service import MAX_LIMIT, SearchService
from vethuq_api.sources_service import SourcesService

HEADERS = {"Origin": ORIGIN}


@pytest.fixture
def library(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "report.md").write_text(
        "# Harvest\nWheat prices rose. Wheat is key.", encoding="utf-8"
    )
    (first / "notes.txt").write_text("Notes about wheat and barley.", encoding="utf-8")
    (second / "memo.txt").write_text("A memo on wheat.", encoding="utf-8")
    (first / "tool.exe").write_bytes(b"MZ")
    return tmp_path


@pytest.fixture
def vethuq(library):
    client = VethuQ(library / "vethuq.db")
    client.settings.index.set_stability_check_seconds(0)
    a = client.sources.create(library / "a")
    client.sources.create(library / "b")
    client.index.run()
    client.first_source = a.id
    yield client
    client.close()


@pytest.fixture
def service(vethuq):
    return SearchService(lambda: vethuq)


class TestOptions:
    def test_engines_normalizers_file_types_and_defaults(self, service):
        data = service.options()
        assert {"like", "exact"} <= {e["id"] for e in data["engines"]}
        assert data["normalizers"] and {t["id"] for t in data["file_types"]} >= {"txt", "markdown"}
        assert all(t["available"] for t in data["file_types"])
        assert data["defaults"]["engine"] and data["defaults"]["context_chars"] > 0


class TestRun:
    def test_a_search_answers_with_matches_each_with_its_file_type(self, service):
        data = service.run({"query": "wheat", "engine": "like"})
        assert data["total"] >= 4 and data["limit"] == 50 and data["offset"] == 0
        kinds = {m["file_name"]: m["file_type"] for m in data["matches"]}
        assert kinds == {"report.md": "markdown", "notes.txt": "txt", "memo.txt": "txt"}
        first = data["matches"][0]
        assert {"before", "matched", "after", "page_number", "engine", "source"} <= set(first)

    def test_file_types_and_sources_narrow_it(self, service, vethuq):
        only_txt = service.run({"query": "wheat", "engine": "like", "file_types": ["txt"]})
        assert {m["file_name"] for m in only_txt["matches"]} == {"notes.txt", "memo.txt"}
        both = service.run({"query": "wheat", "engine": "like", "file_types": ["txt", "markdown"]})
        assert len({m["file_name"] for m in both["matches"]}) == 3
        in_a = service.run({"query": "wheat", "engine": "like", "sources": [vethuq.first_source]})
        assert {m["file_name"] for m in in_a["matches"]} == {"report.md", "notes.txt"}

    def test_case_paging_and_the_cap(self, service):
        match = service.run({"query": "WHEAT", "engine": "like", "case_sensitive": True})
        assert match["total"] == 0
        page = service.run({"query": "wheat", "engine": "like", "limit": 2, "offset": 1})
        assert len(page["matches"]) == 2 and page["offset"] == 1 and page["total"] >= 4
        assert (
            service.run({"query": "wheat", "engine": "like", "limit": 10**6})["limit"] == MAX_LIMIT
        )

    def test_an_empty_query_matches_nothing(self, service):
        assert service.run({"query": "  "})["total"] == 0

    def test_bad_values_are_refused(self, service):
        for body in (
            {"query": 5},
            {"query": "x", "case_sensitive": "yes"},
            {"query": "x", "file_types": "pdf"},
            {"query": "x", "sources": ["a"]},
            {"query": "x", "limit": -1},
            {"query": "x", "normalize": []},
            {"query": "x", "engine": 3},
        ):
            with pytest.raises(ValueError):
                service.run(body)

    def test_a_missing_engine_is_a_readable_error(self, service):
        with pytest.raises(Exception, match="nope|engine"):
            service.run({"query": "wheat", "engine": "nope"})


class TestExport:
    def test_every_match_is_exported_in_the_format_asked(self, service):
        data, name, mime = service.export({"query": "wheat", "engine": "like"}, "json")
        assert name.endswith(".json") and mime == "application/json" and b"report.md" in data
        data, name, mime = service.export({"query": "wheat", "engine": "like"}, "html")
        assert name.endswith(".html") and mime == "text/html" and b"<html" in data.lower()

    def test_a_bad_format_is_refused(self, service):
        with pytest.raises(ValueError):
            service.export({"query": "wheat", "engine": "like"}, "pdf")


class TestOpenGuard:
    def test_only_a_readable_file_inside_a_source_may_be_opened(self, vethuq, library):
        sources = SourcesService(lambda: vethuq)
        assert sources.may_open(str(library / "a" / "notes.txt")) is True
        assert sources.may_open(str(library / "a" / "tool.exe")) is False  # not a kind VethuQ reads
        assert sources.may_open(str(library / "vethuq.db")) is False  # outside every source
        assert sources.may_open(str(library / "a")) is False  # a folder
        assert sources.may_open(str(library / "a" / "missing.txt")) is False
        assert sources.may_open(str(library / "a" / ".." / "vethuq.db")) is False

    def test_a_link_out_of_a_source_does_not_count(self, vethuq, library):
        outside = library / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = library / "a" / "link.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("links need a privilege here")
        assert SourcesService(lambda: vethuq).may_open(str(link)) is False


class TestHttp:
    @pytest.fixture
    def http(self, web_dist, library):
        core = VethuQCore(library / "vethuq.db")
        client = core._vethuq()
        client.settings.index.set_stability_check_seconds(0)
        client.sources.create(library / "a")
        client.index.run()
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        return test

    def post(self, http, url, **body):
        return http.post(f"/api{url}", json=body, base_url=ORIGIN, headers=HEADERS)

    def test_the_endpoints_answer(self, http):
        options = http.get("/api/search/options", base_url=ORIGIN).get_json()
        assert options["engines"]
        found = self.post(http, "/search/run", query="wheat", engine="like").get_json()
        assert found["total"] >= 3 and found["matches"][0]["file_type"]
        export = self.post(http, "/search/export", query="wheat", engine="like", format="json")
        assert "attachment" in export.headers["Content-Disposition"]

    def test_errors_and_the_origin_check(self, http):
        assert self.post(http, "/search/run", query=1).status_code == 422
        assert self.post(http, "/search/run", query="x", engine="nope").status_code == 422
        assert self.post(http, "/search/export", query="x", format=3).status_code == 422
        bare = http.post("/api/search/run", json={"query": "x"}, base_url=ORIGIN)
        assert bare.status_code == 403
        assert self.post(http, "/os/open", path="/etc/passwd").status_code in (404, 422)


class TestOpenOverHttp:
    def test_a_file_of_a_source_opens_and_anything_else_is_refused(self, web_dist, library, window):
        origin = ORIGIN
        core = VethuQCore(library / "vethuq.db")
        client = core._vethuq()
        client.sources.create(library / "a")
        app = create_app(
            bootstrap_token="t",
            web_dist=web_dist,
            core=core,
            window=window,
            host_kind="desktop",
        )
        allow_host(app, "127.0.0.1:5000")
        http = app.test_client()
        http.get("/?t=t", base_url=origin)
        good = http.post(
            "/api/os/open",
            json={"path": str(library / "a" / "notes.txt")},
            base_url=origin,
            headers=HEADERS,
        )
        assert good.status_code == 200 and window.calls == [f"open:{library / 'a' / 'notes.txt'}"]
        placed = http.post(
            "/api/os/open",
            json={"path": str(library / "a" / "notes.txt"), "page": 4, "line": 9, "column": 2},
            base_url=origin,
            headers=HEADERS,
        )
        assert placed.get_json() == {"opened": True, "jumped": True, "hint": None}
        assert window.calls[-1].endswith(":page=4:line=9:column=2")
        for bad_place in ({"page": 0}, {"line": "9"}, {"column": True}):
            refused = http.post(
                "/api/os/open",
                json={"path": str(library / "a" / "notes.txt"), **bad_place},
                base_url=origin,
                headers=HEADERS,
            )
            assert refused.status_code == 422
        for path in (str(library / "a" / "tool.exe"), str(library / "vethuq.db"), 5, None):
            bad = http.post("/api/os/open", json={"path": path}, base_url=origin, headers=HEADERS)
            assert bad.status_code == 422
        assert len(window.calls) == 2


class TestPdfFile:
    """The viewer's file route: a PDF of a source, ranges included, and nothing else."""

    @pytest.fixture
    def http(self, web_dist, library):
        (library / "a" / "doc.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 100 + b"\n%%EOF\n")
        (library / "outside.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        return test

    def get(self, http, path, **headers):
        return http.get(
            "/api/files/pdf", query_string={"path": str(path)}, base_url=ORIGIN, headers=headers
        )

    def test_a_pdf_of_a_source_is_served_inline_and_by_range(self, http, library):
        whole = self.get(http, library / "a" / "doc.pdf")
        assert whole.status_code == 200 and whole.mimetype == "application/pdf"
        assert whole.headers["Content-Disposition"] == "inline"
        assert whole.headers["Cache-Control"] == "no-store"
        assert whole.data.startswith(b"%PDF")
        part = self.get(http, library / "a" / "doc.pdf", Range="bytes=0-7")
        assert part.status_code == 206 and part.data == b"%PDF-1.4"

    def test_anything_else_is_refused(self, http, library):
        for path in (
            library / "outside.pdf",  # outside every source
            library / "a" / "report.md",  # not a PDF
            library / "a" / "missing.pdf",
            library / "a",
        ):
            assert self.get(http, path).status_code == 422, path
        assert http.get("/api/files/pdf", base_url=ORIGIN).status_code == 422

    def test_it_needs_the_session(self, web_dist, library):
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=VethuQCore(library / "x.db"))
        allow_host(app, "127.0.0.1:5000")
        bare = app.test_client().get(
            "/api/files/pdf", query_string={"path": "x.pdf"}, base_url=ORIGIN
        )
        assert bare.status_code in (401, 403)


class TestTextWindow:
    @pytest.fixture
    def http(self, web_dist, library):
        body = "\n".join(f"line {n} of the harvest" for n in range(1, 1201))
        (library / "a" / "long.txt").write_text(body + "\nwheat at the end", encoding="utf-8")
        (library / "a" / "wide.md").write_text("x" * 25000 + "\nnext", encoding="utf-8")
        (library / "a" / "data.csv").write_text("a,b\nwheat,1\n", encoding="utf-8")
        core = VethuQCore(library / "vethuq.db")
        client = core._vethuq()
        client.settings.index.set_stability_check_seconds(0)
        client.sources.create(library / "a")
        client.index.run()
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.docs = {
            m.file_name: m.document_id
            for word in ("wheat", "next")
            for m in client.search.run(word, engine="like")
        }
        return test

    def window(self, http, **query):
        return http.get("/api/files/text", query_string=query, base_url=ORIGIN)

    def test_a_window_of_lines_and_the_total(self, http):
        reply = self.window(http, document_id=http.docs["long.txt"], start=10, count=3).get_json()
        assert reply["total"] == 1201 and reply["start"] == 10
        assert reply["lines"] == [f"line {n} of the harvest" for n in (11, 12, 13)]
        assert reply["file_name"] == "long.txt" and reply["file_type"] == "txt"

    def test_the_last_window_is_short_and_the_count_is_capped(self, http):
        doc = http.docs["long.txt"]
        last = self.window(http, document_id=doc, start=1198, count=50).get_json()
        assert last["lines"][-1] == "wheat at the end" and len(last["lines"]) == 3
        assert len(self.window(http, document_id=doc, count=100000).get_json()["lines"]) == 500

    def test_a_very_long_line_is_clipped(self, http):
        reply = self.window(http, document_id=http.docs["wide.md"]).get_json()
        assert len(reply["lines"][0]) == 10_001 and reply["lines"][0].endswith("…")
        assert reply["lines"][1] == "next"

    def test_bad_requests(self, http):
        assert self.window(http).status_code == 422
        assert self.window(http, document_id="x").status_code == 422
        assert self.window(http, document_id=1, start=-1).status_code == 422
        assert self.window(http, document_id=987654).status_code == 404

    def test_only_text_and_markdown_files(self, http):
        assert self.window(http, document_id=http.docs["data.csv"]).status_code == 422


class TestCsvTable:
    @pytest.fixture
    def http(self, web_dist, library):
        rows = "\n".join(f"name {n},{n * 3}" for n in range(1, 301))
        (library / "a" / "table.csv").write_text(f"name,qty\n{rows}\n", encoding="utf-8")
        (library / "a" / "odd.csv").write_text("id;note\n1;wheat here\n\n2;x\n", encoding="utf-8")
        (library / "outside.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        core = VethuQCore(library / "vethuq.db")
        client = core._vethuq()
        client.sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="table.csv", **query):
        path = http.library / "a" / name
        return http.get(
            "/api/files/csv", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def test_a_window_of_rows_with_the_header_and_sizes(self, http):
        reply = self.get(http, start=10, count=3).get_json()
        assert reply["total"] == 300 and reply["all"] == 300 and reply["header"] == ["name", "qty"]
        assert reply["header_detected"] is True and reply["delimiter"] == ","
        assert reply["rows"] == [["name 11", "33"], ["name 12", "36"], ["name 13", "39"]]
        assert reply["numbers"] == [12, 13, 14]  # the header is row 1
        assert reply["columns"] == 2 and len(reply["widths"]) == 2

    def test_sorting_filtering_and_the_header_switch(self, http):
        down = self.get(http, sort=1, dir="desc", count=2).get_json()
        assert down["rows"][0] == ["name 300", "900"]
        found = self.get(http, **{"filter": "name 29", "column": 0}).get_json()
        assert found["total"] == 11 and found["all"] == 300
        plain = self.get(http, header=0, count=1).get_json()
        assert (
            plain["header"] is None and plain["rows"] == [["name", "qty"]] and plain["total"] == 301
        )

    def test_where_a_match_is(self, http):
        # Row 3 of odd.csv is "2;x" (the empty row is not counted): indexed as "2 | x".
        reply = self.get(http, "odd.csv", at_row=3, at_offset=5).get_json()
        assert reply["target"] == {"row_number": 3, "index": 1, "column": 1}
        assert reply["numbers"] == [2, 3]
        sorted_ = self.get(http, "table.csv", sort=1, dir="desc", at_row=2, at_offset=1).get_json()
        assert sorted_["target"]["index"] == 299  # the smallest quantity is last

    def test_only_a_csv_of_a_source(self, http):
        assert self.get(http, "table.csv").status_code == 200
        assert (
            http.get(
                "/api/files/csv",
                query_string={"path": str(http.library / "outside.csv")},
                base_url=ORIGIN,
            ).status_code
            == 422
        )
        assert self.get(http, "notes.txt").status_code == 422
        assert self.get(http, "missing.csv").status_code == 422
        for bad in ({"dir": "up"}, {"start": "x"}, {"count": 0}, {"header": "2"}):
            assert self.get(http, **bad).status_code == 422, bad


class TestTsvTable:
    @pytest.fixture
    def http(self, web_dist, library):
        rows = "\n".join(f"name {n}\t{n * 3}" for n in range(1, 301))
        (library / "a" / "table.tsv").write_text(f"name\tqty\n{rows}\n", encoding="utf-8")
        # Commas and semicolons are text in a TSV file, not delimiters.
        (library / "a" / "odd.tsv").write_text("id\tnote\n1\twheat, here; ok\n\n2\tx\n", "utf-8")
        (library / "a" / "plain.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (library / "outside.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="table.tsv", route="tsv", **query):
        path = http.library / "a" / name
        return http.get(
            f"/api/files/{route}", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def test_a_window_of_rows_with_the_header_and_sizes(self, http):
        reply = self.get(http, start=10, count=3).get_json()
        assert reply["total"] == 300 and reply["header"] == ["name", "qty"]
        assert reply["delimiter"] == "\t" and reply["header_detected"] is True
        assert reply["rows"] == [["name 11", "33"], ["name 12", "36"], ["name 13", "39"]]
        assert reply["numbers"] == [12, 13, 14]  # the header is row 1

    def test_only_a_tab_separates_cells(self, http):
        reply = self.get(http, "odd.tsv").get_json()
        assert reply["columns"] == 2 and reply["rows"][0] == ["1", "wheat, here; ok"]

    def test_where_a_match_is(self, http):
        # Row 3 of odd.tsv is "2<tab>x" (the empty row is not counted): indexed as "2 | x".
        reply = self.get(http, "odd.tsv", at_row=3, at_offset=5).get_json()
        assert reply["target"] == {"row_number": 3, "index": 1, "column": 1}

    def test_sorting_and_filtering(self, http):
        down = self.get(http, sort=1, dir="desc", count=1).get_json()
        assert down["rows"] == [["name 300", "900"]]
        assert self.get(http, **{"filter": "name 29", "column": 0}).get_json()["total"] == 11

    def test_only_a_tsv_of_a_source(self, http):
        assert self.get(http).status_code == 200
        outside = {"path": str(http.library / "outside.tsv")}
        assert http.get("/api/files/tsv", query_string=outside, base_url=ORIGIN).status_code == 422
        assert self.get(http, "plain.csv").status_code == 422
        assert self.get(http, "missing.tsv").status_code == 422
        # The CSV route does not take a TSV file, nor the TSV route a CSV one.
        assert self.get(http, route="csv").status_code == 422


class TestMarkdownFile:
    @pytest.fixture
    def http(self, web_dist, library):
        (library / "a" / "big.md").write_text("# Title\n\nSome **bold** text.\n", encoding="utf-8")
        (library / "outside.md").write_text("# Out\n", encoding="utf-8")
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, path):
        return http.get("/api/files/markdown", query_string={"path": str(path)}, base_url=ORIGIN)

    def test_the_file_as_it_is_on_disk(self, http):
        reply = self.get(http, http.library / "a" / "big.md").get_json()
        assert reply["text"] == "# Title\n\nSome **bold** text.\n"
        assert reply["file_name"] == "big.md" and reply["encoding"] == "utf-8"

    def test_only_a_markdown_file_of_a_source(self, http, monkeypatch):
        for path in (
            http.library / "outside.md",
            http.library / "a" / "notes.txt",
            http.library / "a" / "missing.md",
        ):
            assert self.get(http, path).status_code == 422, path
        assert http.get("/api/files/markdown", base_url=ORIGIN).status_code == 422
        monkeypatch.setattr("vethuq_api.search_service.SOURCE_MAX_BYTES", 5)
        assert self.get(http, http.library / "a" / "big.md").status_code == 422


SOURCES = {
    "css": ("a{color:red}\n/* note */\n", ".css", "a stylesheet"),
    "html": ("<html><body><p>Hello <b>world</b></p></body></html>", ".html", "a web page"),
    "json": ('{"server": {"ports": [8080, 8081]}}', ".json", "a JSON file"),
    "yaml": ("server:\n  ports:\n    - 8080\n", ".yaml", "a YAML file"),
    "ndjson": ('{"a": 1}\n{"a": 2}\n', ".ndjson", "an NDJSON file"),
    "js": ("const a = 1;\n\nexport default a;\n", ".mjs", "a script"),
    "xml": (
        '<?xml version="1.0"?><catalog><book id="7">Dune</book></catalog>',
        ".xml",
        "an XML file",
    ),
}


@pytest.mark.parametrize("kind", sorted(SOURCES))
class TestSourceFiles:
    """The routes for files the preview shows as they are on disk, a route for each type. The
    add-ons of these types are licensed code that this checkout may not have, so the type checks
    are replaced where one is missing; what is tested is the route and the file."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch, kind):
        text, extension, _ = SOURCES[kind]
        (library / "a" / f"sample{extension}").write_text(text, encoding="utf-8")
        (library / f"outside{extension}").write_text(text, encoding="utf-8")
        probe = VethuQ(library / "probe.db")
        try:
            try:
                installed = probe.file_types.get(kind).available
            except FileTypeUnavailableError:
                installed = False
        finally:
            probe.close()
        if not installed:
            monkeypatch.setattr(
                SearchService,
                "is_type",
                lambda self, path, wanted: wanted == kind and path.lower().endswith(extension),
            )
            real = SourcesService.may_open
            inside = os.path.realpath(library / "a")

            def may_open(self, path):
                real_path = os.path.realpath(path)
                return real(self, path) or (
                    os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
                )

            monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, kind, path):
        return http.get(f"/api/files/{kind}", query_string={"path": str(path)}, base_url=ORIGIN)

    def test_the_file_as_it_is_on_disk_with_its_longest_line(self, http, kind):
        text, extension, _ = SOURCES[kind]
        reply = self.get(http, kind, http.library / "a" / f"sample{extension}").get_json()
        assert reply["text"] == text
        assert reply["file_name"] == f"sample{extension}"
        assert reply["longest_line"] == max(len(line) for line in text.split("\n"))

    def test_only_a_file_of_that_type_in_a_source(self, http, kind):
        _, extension, what = SOURCES[kind]
        for path in (
            http.library / f"outside{extension}",
            http.library / "a" / "notes.txt",
            http.library / "a" / f"missing{extension}",
        ):
            assert self.get(http, kind, path).status_code == 422, path
        bare = http.get(f"/api/files/{kind}", base_url=ORIGIN)
        assert bare.status_code == 422 and what in bare.get_json()["error"]


PICTURES = {"png": ".png", "jpg": ".jpg", "tiff": ".tiff"}


@pytest.mark.parametrize("kind", sorted(PICTURES))
class TestPictures:
    """The picture routes: a JPEG and a PNG as they are, a TIFF one frame at a time as a PNG. The
    add-ons of these types may be missing here, so the type checks are replaced as for the other
    files; what is tested is the route and the file."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch, kind):
        from PIL import Image

        extension = PICTURES[kind]
        red = Image.new("RGB", (40, 20), (255, 0, 0))
        blue = Image.new("RGB", (30, 50), (0, 0, 255))
        target = library / "a" / f"sample{extension}"
        if kind == "tiff":
            red.save(target, save_all=True, append_images=[blue])
        else:
            red.save(target)
        red.save(library / f"outside{extension}")
        probe = VethuQ(library / "probe.db")
        try:
            try:
                installed = probe.file_types.get(kind).available
            except FileTypeUnavailableError:
                installed = False
        finally:
            probe.close()
        if not installed:
            monkeypatch.setattr(
                SearchService,
                "is_type",
                lambda self, path, wanted: wanted == kind and path.lower().endswith(extension),
            )
            real = SourcesService.may_open
            inside = os.path.realpath(library / "a")

            def may_open(self, path):
                real_path = os.path.realpath(path)
                return real(self, path) or (
                    os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
                )

            monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, kind, path, **query):
        return http.get(
            f"/api/files/{kind}", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def size(self, reply):
        import io

        from PIL import Image

        picture = Image.open(io.BytesIO(reply.data))
        return picture.format, picture.size

    def test_the_picture_is_served_inline(self, http, kind):
        extension = PICTURES[kind]
        reply = self.get(http, kind, http.library / "a" / f"sample{extension}")
        assert reply.status_code == 200 and reply.headers["Content-Disposition"] == "inline"
        assert reply.mimetype == ("image/jpeg" if kind == "jpg" else "image/png")
        assert reply.headers["Cache-Control"] == "no-store"
        assert self.size(reply) == ("JPEG" if kind == "jpg" else "PNG", (40, 20))

    def test_only_a_picture_of_that_type_in_a_source(self, http, kind):
        extension = PICTURES[kind]
        for path in (
            http.library / f"outside{extension}",
            http.library / "a" / "notes.txt",
            http.library / "a" / f"missing{extension}",
        ):
            assert self.get(http, kind, path).status_code == 422, path
        assert http.get(f"/api/files/{kind}", base_url=ORIGIN).status_code == 422


class TestTiffFrames:
    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        from PIL import Image

        extension = ".tiff"
        frames = [
            Image.new("RGB", (40, 20), (255, 0, 0)),
            Image.new("L", (30, 50), 128),
            Image.new("CMYK", (10, 10), (0, 255, 255, 0)),
        ]
        frames[0].save(library / "a" / "scan.tiff", save_all=True, append_images=frames[1:])
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "tiff" and path.lower().endswith(extension),
        )
        monkeypatch.setattr(SourcesService, "may_open", lambda self, path: os.path.isfile(path))
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def frame(self, http, **query):
        return http.get(
            "/api/files/tiff",
            query_string={"path": str(http.library / "a" / "scan.tiff"), **query},
            base_url=ORIGIN,
        )

    def png(self, reply):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(reply.data))

    def test_each_frame_is_a_png_of_its_own_size(self, http):
        first = self.png(self.frame(http))
        assert (first.format, first.size) == ("PNG", (40, 20))
        second = self.png(self.frame(http, page=2))
        assert second.size == (30, 50)
        third = self.png(self.frame(http, page=3))  # CMYK is brought to ordinary colour
        assert third.mode in ("RGB", "RGBA") and third.size == (10, 10)

    def test_a_frame_that_is_not_there_or_not_a_number(self, http):
        for page in (0, 4, "x", -1):
            assert self.frame(http, page=page).status_code == 422, page

    def test_a_frame_that_is_too_large_is_refused(self, http, monkeypatch):
        monkeypatch.setattr("vethuq_api.images.MAX_PIXELS", 500)
        reply = self.frame(http, page=2)  # 30 x 50 = 1500 pixels
        assert reply.status_code == 422 and "too large to preview" in reply.get_json()["error"]
        assert self.frame(http, page=3).status_code == 200  # 100 pixels

    def test_a_16_bit_frame_is_scaled_to_eight_bits(self, http):
        import numpy as np
        from PIL import Image

        grey = Image.fromarray(np.array([[0, 1000], [2000, 4000]], dtype=np.uint16))
        grey.save(http.library / "a" / "scan.tiff")
        picture = self.png(self.frame(http))
        assert picture.mode == "L" and picture.getextrema() == (0, 255)


class TestParquetTable:
    """The table preview of a Parquet file. The add-on is licensed code that this checkout may not
    have, so the type checks are replaced; what is tested is the route and the file."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        pq = pytest.importorskip("pyarrow.parquet")
        import pyarrow as pa

        rows = range(1, 301)
        data = {"name": [f"name {n}" for n in rows], "qty": [n * 3 for n in rows]}
        pq.write_table(pa.table(data), library / "a" / "table.parquet", row_group_size=100)
        pq.write_table(pa.table({"id": [1, 2, 3]}), library / "outside.parquet")
        (library / "a" / "plain.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
        (library / "a" / "bad.parquet").write_bytes(b"not a table")
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "parquet" and path.lower().endswith(".parquet"),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(library / "a")

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="table.parquet", **query):
        path = http.library / "a" / name
        return http.get(
            "/api/files/parquet", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def test_a_window_of_rows_with_the_column_names_as_the_header(self, http):
        reply = self.get(http, start=10, count=3).get_json()
        assert reply["total"] == 300 and reply["header"] == ["name", "qty"]
        assert reply["header_detected"] is True and reply["truncated"] is False
        assert reply["encoding"] == "parquet" and reply["columns"] == 2
        assert reply["rows"] == [["name 11", "33"], ["name 12", "36"], ["name 13", "39"]]
        assert reply["numbers"] == [
            12,
            13,
            14,
        ]  # the column names are row 1, as a match's line says

    def test_sorting_and_filtering(self, http):
        down = self.get(http, sort=1, dir="desc", count=1).get_json()
        assert down["rows"] == [["name 300", "900"]]
        found = self.get(http, **{"filter": "name 29", "column": 0}).get_json()
        assert found["total"] == 11 and found["all"] == 300

    def test_where_a_match_is(self, http):
        # Line 3 of the indexed text is row 3: "name 2 | 6"; offset 8 is inside "name 2".
        reply = self.get(http, at_row=3, at_offset=8).get_json()
        assert reply["target"] == {"row_number": 3, "index": 1, "column": 0}

    def test_only_a_parquet_file_of_a_source(self, http):
        assert self.get(http).status_code == 200
        outside = {"path": str(http.library / "outside.parquet")}
        assert (
            http.get("/api/files/parquet", query_string=outside, base_url=ORIGIN).status_code == 422
        )
        assert self.get(http, "plain.tsv").status_code == 422
        assert self.get(http, "missing.parquet").status_code == 422

    def test_a_damaged_file_says_why(self, http):
        reply = self.get(http, "bad.parquet")
        assert reply.status_code == 422
        assert "not a readable Parquet file" in reply.get_json()["error"]


class TestMhtmlPage:
    """A web archive made into one page for the preview. The add-on is licensed code that this
    checkout may not have, so the type checks are replaced; what is tested is the route and the
    file (a real Chromium capture)."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        fixture = Path(__file__).parent / "fixtures" / "chrome.mhtml"
        (library / "a" / "page.mhtml").write_bytes(fixture.read_bytes())
        (library / "a" / "plain.html").write_text("<p>x</p>", encoding="utf-8")
        (library / "a" / "broken.mhtml").write_bytes(b"not an archive")
        (library / "outside.mhtml").write_bytes(fixture.read_bytes())
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "mhtml" and path.lower().endswith(".mhtml"),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(library / "a")

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(library / "a")
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="page.mhtml"):
        path = http.library / "a" / name
        return http.get("/api/files/mhtml", query_string={"path": str(path)}, base_url=ORIGIN)

    def test_it_gives_the_source_and_the_self_contained_page(self, http):
        reply = self.get(http).get_json()
        assert reply["file_name"] == "page.mhtml" and reply["encoding"] == "utf-8"
        assert reply["address"] == "http://127.0.0.1:8765/index.html" and reply["frame_count"] == 1
        assert 'src="http://127.0.0.1:8765/scan.png"' in reply["text"]  # as written
        assert 'src="data:image/png;base64,' in reply["rendered"]  # made self-contained
        assert reply["incomplete"] is False and reply["longest_line"] > 0

    def test_only_an_mhtml_file_of_a_source(self, http):
        assert self.get(http).status_code == 200
        outside = {"path": str(http.library / "outside.mhtml")}
        assert (
            http.get("/api/files/mhtml", query_string=outside, base_url=ORIGIN).status_code == 422
        )
        assert self.get(http, "plain.html").status_code == 422
        assert self.get(http, "missing.mhtml").status_code == 422

    def test_a_file_that_is_not_an_archive_says_why(self, http):
        reply = self.get(http, "broken.mhtml")
        assert reply.status_code == 422 and "not a web archive" in reply.get_json()["error"]

    def test_it_needs_the_session(self, web_dist, library):
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=VethuQCore(library / "x.db"))
        allow_host(app, "127.0.0.1:5000")
        bare = app.test_client().get(
            "/api/files/mhtml", query_string={"path": "x.mhtml"}, base_url=ORIGIN
        )
        assert bare.status_code in (401, 403)


class TestBmpPicture:
    """A BMP made into a PNG a browser can show. The BMP add-on may not be installed in this
    checkout, so the type check is replaced; what is tested is the route and the pictures."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        import struct

        from PIL import Image

        folder = library / "a"
        Image.new("RGB", (40, 20), (200, 20, 10)).save(folder / "plain.bmp")

        def info(width, height, bpp, compression=0, size=40, clrused=0, image=0):
            return struct.pack(
                "<IiiHHIIiiII",
                size,
                width,
                height,
                1,
                bpp,
                compression,
                image,
                2835,
                2835,
                clrused,
                0,
            )

        def bmp(body, offset):
            return b"BM" + struct.pack("<IHHI", 14 + len(body), 0, 0, offset) + body

        # Run-length encoded: four red pixels on the bottom row, four black on the top.
        palette = bytes([0, 0, 0, 0, 0, 0, 255, 0])
        rle = bytes([4, 1, 0, 0, 4, 0, 0, 1])
        body = info(4, 2, 8, compression=1, clrused=2, image=len(rle)) + palette + rle
        (folder / "rle.bmp").write_bytes(bmp(body, 14 + 40 + 8))
        # A BITMAPV4 header that says there is alpha, with every alpha byte 0.
        mask = struct.pack("<IIII", 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
        header = struct.pack("<IiiHHIIiiII", 108, 2, 1, 1, 32, 3, 0, 2835, 2835, 0, 0) + mask
        header += b"\0" * (108 - len(header))
        (folder / "unused-alpha.bmp").write_bytes(bmp(header + bytes([0, 0, 255, 0]) * 2, 14 + 108))
        # What the clipboard holds: a DIB with no file header.
        (folder / "clip.dib").write_bytes(info(2, 1, 24) + bytes([0, 0, 255] * 2) + b"\0\0")
        (folder / "notes.bmp").write_bytes(b"this is not a bitmap")
        Image.new("RGB", (30, 50)).save(library / "outside.bmp")
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "bmp" and path.lower().endswith((".bmp", ".dib")),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(folder)

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(folder)
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name):
        path = http.library / "a" / name
        return http.get("/api/files/bmp", query_string={"path": str(path)}, base_url=ORIGIN)

    def picture(self, reply):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(reply.data)).convert("RGB")

    def test_a_bmp_is_served_as_a_png_of_its_own_size(self, http):
        reply = self.get(http, "plain.bmp")
        assert reply.status_code == 200 and reply.mimetype == "image/png"
        assert reply.headers["Content-Disposition"] == "inline"
        picture = self.picture(reply)
        assert picture.size == (40, 20) and picture.getpixel((0, 0)) == (200, 20, 10)

    def test_a_run_length_encoded_bitmap_is_drawn(self, http):
        picture = self.picture(self.get(http, "rle.bmp"))
        assert picture.getpixel((0, 1)) == (255, 0, 0) and picture.getpixel((0, 0)) == (0, 0, 0)

    def test_an_unused_alpha_byte_does_not_make_a_blank_picture(self, http):
        picture = self.picture(self.get(http, "unused-alpha.bmp"))
        assert picture.getpixel((0, 0)) == (255, 0, 0)

    def test_a_headerless_dib_is_drawn(self, http):
        assert self.picture(self.get(http, "clip.dib")).getpixel((0, 0)) == (255, 0, 0)

    def test_only_a_bmp_of_a_source(self, http):
        outside = {"path": str(http.library / "outside.bmp")}
        assert http.get("/api/files/bmp", query_string=outside, base_url=ORIGIN).status_code == 422
        assert self.get(http, "missing.bmp").status_code == 422
        assert self.get(http, "plain.bmp").status_code == 200

    def test_a_file_that_is_not_a_bitmap_is_refused_with_a_reason(self, http):
        reply = self.get(http, "notes.bmp")
        assert reply.status_code == 422 and "not a BMP" in reply.get_json()["error"]

    def test_a_bitmap_that_is_cut_off_is_refused_with_a_reason(self, http):
        path = http.library / "a" / "cut.bmp"
        data = (http.library / "a" / "plain.bmp").read_bytes()
        path.write_bytes(data[: len(data) // 2])
        reply = self.get(http, "cut.bmp")
        assert reply.status_code == 422 and "damaged" in reply.get_json()["error"]

    def test_a_picture_that_is_too_large_is_refused(self, http, monkeypatch):
        monkeypatch.setattr("vethuq_api.images.MAX_PIXELS", 500)
        reply = self.get(http, "plain.bmp")  # 40 x 20 = 800 pixels
        assert reply.status_code == 422
        assert (
            "This picture is" in reply.get_json()["error"]
            and "too large" in reply.get_json()["error"]
        )


class TestGifPictures:
    """A GIF shown one page (distinct picture) at a time as a PNG. The GIF add-on may not be
    installed in this checkout, so the type check is replaced; the route and the pictures are
    what is tested."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        from PIL import Image, ImageDraw

        folder = library / "a"

        def gif(name, frames, **kw):
            frames[0].save(
                folder / name, "GIF", save_all=len(frames) > 1, append_images=frames[1:], **kw
            )

        red, green, blue = (
            Image.new("RGB", (40, 20), colour) for colour in ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        )
        gif("three.gif", [red, green, blue], duration=100, loop=0)
        gif("loop.gif", [red, green] * 3, duration=100, loop=0)
        gif("still.gif", [red])
        ink = Image.new("P", (30, 30), 0)  # index 0 transparent, index 1 black ink
        ink.putpalette([255, 255, 255, 0, 0, 0] + [0, 0, 0] * 254)
        ImageDraw.Draw(ink).rectangle([10, 10, 20, 20], fill=1)
        gif("transparent.gif", [ink], transparency=0)
        (folder / "notes.gif").write_bytes(b"this is not a picture")
        red.save(library / "outside.gif", "GIF")
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "gif" and path.lower().endswith(".gif"),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(folder)

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(folder)
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="three.gif", **query):
        path = http.library / "a" / name
        return http.get(
            "/api/files/gif", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def picture(self, reply):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(reply.data)).convert("RGB")

    def test_each_page_is_a_png_of_that_picture(self, http):
        first = self.get(http)
        assert first.status_code == 200 and first.mimetype == "image/png"
        assert first.headers["Content-Disposition"] == "inline"
        assert self.picture(first).size == (40, 20)
        assert self.picture(first).getpixel((0, 0)) == (255, 0, 0)
        assert self.picture(self.get(http, page=2)).getpixel((0, 0)) == (0, 255, 0)
        assert self.picture(self.get(http, page=3)).getpixel((0, 0)) == (0, 0, 255)

    def test_a_loop_is_two_pages_not_six(self, http):
        assert self.get(http, "loop.gif", page=2).status_code == 200
        reply = self.get(http, "loop.gif", page=3)
        assert reply.status_code == 422 and "has 2 frames" in reply.get_json()["error"]

    def test_a_still_gif_is_one_page(self, http):
        assert self.get(http, "still.gif").status_code == 200
        reply = self.get(http, "still.gif", page=2)
        assert reply.status_code == 422 and "has 1 frame." in reply.get_json()["error"]

    def test_a_page_that_is_not_there_or_not_a_number(self, http):
        for page in (0, 4, "x", -1):
            assert self.get(http, page=page).status_code == 422, page

    def test_transparency_is_laid_on_white_so_ink_shows_on_any_theme(self, http):
        picture = self.picture(self.get(http, "transparent.gif"))
        assert picture.getpixel((0, 0)) == (255, 255, 255)
        assert picture.getpixel((15, 15)) == (0, 0, 0)

    def test_only_a_gif_of_a_source(self, http):
        outside = {"path": str(http.library / "outside.gif")}
        assert http.get("/api/files/gif", query_string=outside, base_url=ORIGIN).status_code == 422
        assert self.get(http, "missing.gif").status_code == 422

    def test_a_file_that_is_not_a_gif_says_why(self, http):
        reply = self.get(http, "notes.gif")
        assert reply.status_code == 422 and "not a GIF" in reply.get_json()["error"]

    def test_a_picture_that_is_too_large_is_refused(self, http, monkeypatch):
        monkeypatch.setattr("vethuq_api.images.MAX_PIXELS", 500)
        reply = self.get(http)  # 40 x 20 = 800 pixels
        assert reply.status_code == 422 and "too large to preview" in reply.get_json()["error"]


class TestGifPagesAreTheOnesTheAddOnReads:
    """The preview shows the picture that was read: its pages are the add-on's, one for one. This
    needs the GIF add-on (installed with the image bundle), so it is skipped without it."""

    def animations(self, tmp_path):
        from PIL import Image, ImageDraw

        def solid(colour):
            return Image.new("RGB", (60, 30), colour)

        base = solid((200, 200, 200))
        captioned = base.copy()
        ImageDraw.Draw(captioned).rectangle([40, 20, 50, 28], fill=(0, 0, 0))
        cases = {
            "still": [solid((9, 9, 9))],
            "loop": [solid((255, 0, 0)), solid((0, 255, 0))] * 4,
            "returns": [
                solid((255, 0, 0)),
                solid((0, 255, 0)),
                solid((255, 0, 0)),
                solid((0, 0, 255)),
            ],
            "partial": [base, captioned, base, captioned],
            "many": [solid((n * 7, 0, 0)) for n in range(1, 41)],  # more than the page limit
        }
        paths = {}
        for name, frames in cases.items():
            path = tmp_path / f"{name}.gif"
            frames[0].save(
                path,
                "GIF",
                save_all=len(frames) > 1,
                append_images=frames[1:],
                optimize=name == "partial",
            )
            paths[name] = path
        return paths

    def test_the_same_number_of_pages_and_the_same_pictures(self, tmp_path):
        import io

        from PIL import Image

        reader = pytest.importorskip("vethuq_addon_gif.reader")
        from vethuq_api import images

        for name, path in self.animations(tmp_path).items():
            read = []
            for page in reader.GifReader().read(path):
                read.append(page.render(None)[:, :, ::-1].copy())  # BGR to RGB
            assert images.gif_pages(str(path)) == len(read), name
            for number, expected in enumerate(read, start=1):
                shown = Image.open(io.BytesIO(images.gif_page_as_png(str(path), number)))
                assert shown.convert("RGB").tobytes() == expected.tobytes(), (name, number)

    def test_the_limits_match(self):
        reader = pytest.importorskip("vethuq_addon_gif.reader")
        from vethuq_api import images

        assert images.ANIMATION_MAX_PAGES == reader.GifReader.MAX_PAGES
        assert images.ANIMATION_MAX_SCAN_FRAMES == reader.GifReader.MAX_SCAN_FRAMES


class TestWebpPictures:
    """A WebP shown one page at a time as a PNG (a still is one page, an animation has one for each
    distinct picture). The WebP add-on may not be installed in this checkout, so the type check is
    replaced; the route and the pictures are what is tested."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        from PIL import Image, ImageDraw

        folder = library / "a"

        def webp(name, frames, **kw):
            frames[0].save(
                folder / name,
                "WEBP",
                save_all=len(frames) > 1,
                append_images=frames[1:],
                lossless=True,
                **kw,
            )

        red, green, blue = (
            Image.new("RGB", (40, 20), colour) for colour in ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        )
        webp("three.webp", [red, green, blue], duration=100, loop=0)
        webp("loop.webp", [red, green] * 3, duration=100, loop=0)
        webp("still.webp", [red])
        ink = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
        ImageDraw.Draw(ink).rectangle([10, 10, 20, 20], fill=(0, 0, 0, 255))
        webp("transparent.webp", [ink])
        exif = Image.Exif()
        exif[0x0112] = 6  # shown turned a quarter: 40 x 20 is displayed as 20 x 40
        webp("turned.webp", [red], exif=exif.tobytes())
        (folder / "notes.webp").write_bytes(b"this is not a picture")
        data = (folder / "three.webp").read_bytes()
        (folder / "cut.webp").write_bytes(data[: len(data) // 2])
        red.save(library / "outside.webp", "WEBP")
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "webp" and path.lower().endswith(".webp"),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(folder)

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(folder)
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="three.webp", **query):
        path = http.library / "a" / name
        return http.get(
            "/api/files/webp", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def picture(self, reply):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(reply.data)).convert("RGB")

    def test_each_page_is_a_png_of_that_picture(self, http):
        first = self.get(http)
        assert first.status_code == 200 and first.mimetype == "image/png"
        assert first.headers["Content-Disposition"] == "inline"
        assert self.picture(first).size == (40, 20)
        assert self.picture(first).getpixel((0, 0)) == (255, 0, 0)
        assert self.picture(self.get(http, page=2)).getpixel((0, 0)) == (0, 255, 0)
        assert self.picture(self.get(http, page=3)).getpixel((0, 0)) == (0, 0, 255)

    def test_a_loop_is_two_pages_not_six(self, http):
        assert self.get(http, "loop.webp", page=2).status_code == 200
        reply = self.get(http, "loop.webp", page=3)
        assert reply.status_code == 422 and "has 2 frames" in reply.get_json()["error"]

    def test_a_still_is_one_page(self, http):
        assert self.get(http, "still.webp").status_code == 200
        assert self.get(http, "still.webp", page=2).status_code == 422

    def test_a_page_that_is_not_there_or_not_a_number(self, http):
        for page in (0, 4, "x", -1):
            assert self.get(http, page=page).status_code == 422, page

    def test_transparency_is_laid_on_white_so_ink_shows_on_any_theme(self, http):
        picture = self.picture(self.get(http, "transparent.webp"))
        assert picture.getpixel((0, 0)) == (255, 255, 255)
        assert picture.getpixel((15, 15)) == (0, 0, 0)

    def test_the_orientation_is_applied_so_the_picture_is_the_one_ocr_read(self, http):
        assert self.picture(self.get(http, "turned.webp")).size == (20, 40)

    def test_only_a_webp_of_a_source(self, http):
        outside = {"path": str(http.library / "outside.webp")}
        assert http.get("/api/files/webp", query_string=outside, base_url=ORIGIN).status_code == 422
        assert self.get(http, "missing.webp").status_code == 422

    def test_damaged_files_say_so_and_never_give_a_server_error(self, http):
        for name in ("notes.webp", "cut.webp"):
            reply = self.get(http, name)
            assert reply.status_code == 422, name
            assert "cannot be read" in reply.get_json()["error"], name

    def test_a_picture_that_is_too_large_is_refused(self, http, monkeypatch):
        monkeypatch.setattr("vethuq_api.images.MAX_PIXELS", 500)
        reply = self.get(http)  # 40 x 20 = 800 pixels
        assert reply.status_code == 422 and "too large to preview" in reply.get_json()["error"]

    def test_a_picture_pillow_only_warns_about_is_refused_too(self, http, monkeypatch):
        from PIL import Image

        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 500)  # 800 pixels: a warning, not an error
        reply = self.get(http, "still.webp")
        assert reply.status_code == 422 and "cannot be read" in reply.get_json()["error"]


class TestHeicPictures:
    """A HEIC shown one picture at a time as a PNG (no browser but Safari draws HEIC). The HEIC
    add-on may not be installed in this checkout, so the type check is replaced; the route and the
    pictures are what is tested."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        pillow_heif = pytest.importorskip("pillow_heif")
        from PIL import Image, ImageDraw

        folder = library / "a"

        def heic(name, images, primary=None, **kw):
            file = pillow_heif.HeifFile()
            for image in images:
                file.add_from_pillow(image)
            file.save(folder / name, quality=90, primary_index=primary, **kw)

        red, green, blue = (
            Image.new("RGB", (40, 20), colour) for colour in ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        )
        heic("three.heic", [red, green, blue], primary=0)
        heic("primary.heic", [red, green, blue], primary=2)
        heic("still.heic", [red])
        ink = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(ink).rectangle([20, 20, 44, 44], fill=(0, 0, 0, 255))
        heic("transparent.heic", [ink])
        exif = Image.Exif()
        exif[0x0112] = 6  # shown turned a quarter: 40 x 20 is displayed as 20 x 40
        heic("turned.heic", [red], exif=exif.tobytes())
        (folder / "notes.heic").write_bytes(b"this is not a picture")
        data = (folder / "three.heic").read_bytes()
        (folder / "cut.heic").write_bytes(data[: len(data) // 2])
        red.save(library / "outside.png", "PNG")
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "heic" and path.lower().endswith(".heic"),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(folder)

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(folder)
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="three.heic", **query):
        path = http.library / "a" / name
        return http.get(
            "/api/files/heic", query_string={"path": str(path), **query}, base_url=ORIGIN
        )

    def picture(self, reply):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(reply.data)).convert("RGB")

    @staticmethod
    def is_colour(pixel, expected):
        return all(abs(a - b) <= 12 for a, b in zip(pixel, expected, strict=True))

    def test_each_page_is_a_png_of_that_picture(self, http):
        first = self.get(http)
        assert first.status_code == 200 and first.mimetype == "image/png"
        assert first.headers["Content-Disposition"] == "inline"
        assert self.picture(first).size == (40, 20)
        assert self.is_colour(self.picture(first).getpixel((20, 10)), (255, 0, 0))
        assert self.is_colour(self.picture(self.get(http, page=2)).getpixel((20, 10)), (0, 255, 0))
        assert self.is_colour(self.picture(self.get(http, page=3)).getpixel((20, 10)), (0, 0, 255))

    def test_the_primary_picture_is_the_first_page(self, http):
        pages = [
            self.picture(self.get(http, "primary.heic", page=n)).getpixel((20, 10))
            for n in (1, 2, 3)
        ]
        expected = [(0, 0, 255), (255, 0, 0), (0, 255, 0)]
        assert all(self.is_colour(p, e) for p, e in zip(pages, expected, strict=True))

    def test_a_still_is_one_page(self, http):
        assert self.get(http, "still.heic").status_code == 200
        reply = self.get(http, "still.heic", page=2)
        assert reply.status_code == 422 and "has 1 frame" in reply.get_json()["error"]

    def test_a_page_that_is_not_there_or_not_a_number(self, http):
        for page in (0, 4, "x", -1):
            assert self.get(http, page=page).status_code == 422, page

    def test_transparency_is_laid_on_white_so_ink_shows_on_any_theme(self, http):
        picture = self.picture(self.get(http, "transparent.heic"))
        assert self.is_colour(picture.getpixel((2, 2)), (255, 255, 255))
        assert self.is_colour(picture.getpixel((32, 32)), (0, 0, 0))

    def test_the_orientation_is_applied_once(self, http):
        assert self.picture(self.get(http, "turned.heic")).size == (20, 40)

    def test_only_a_heic_of_a_source(self, http):
        outside = {"path": str(http.library / "outside.png")}
        assert http.get("/api/files/heic", query_string=outside, base_url=ORIGIN).status_code == 422
        assert self.get(http, "missing.heic").status_code == 422

    def test_damaged_files_say_so_and_never_give_a_server_error(self, http):
        for name in ("notes.heic", "cut.heic"):
            reply = self.get(http, name)
            assert reply.status_code == 422, name
            assert "cannot be read" in reply.get_json()["error"], name

    def test_a_picture_that_is_too_large_is_refused(self, http, monkeypatch):
        monkeypatch.setattr("vethuq_api.images.MAX_PIXELS", 500)
        reply = self.get(http)  # 40 x 20 = 800 pixels
        assert reply.status_code == 422 and "too large to preview" in reply.get_json()["error"]

    def test_a_picture_over_pillows_limit_is_refused_too(self, http, monkeypatch):
        from PIL import Image

        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 500)  # pillow-heif makes no check itself
        reply = self.get(http, "still.heic")
        assert reply.status_code == 422 and "cannot be read" in reply.get_json()["error"]


class TestHeicConverterNeverGivesAnUnhandledError:
    def test_every_cut_and_flip_is_either_a_picture_or_a_readable_error(self, tmp_path):
        pillow_heif = pytest.importorskip("pillow_heif")
        from PIL import Image

        from vethuq_api import images

        file = pillow_heif.HeifFile()
        file.add_from_pillow(Image.effect_noise((120, 90), 80).convert("RGB"))
        source = tmp_path / "a.heic"
        file.save(source, quality=90)
        data = source.read_bytes()
        path = tmp_path / "damaged.heic"
        outcomes = set()
        step = max(1, len(data) // 150)
        for cut in range(0, len(data) - 1, step):
            for damaged in (data[:cut], data[:cut] + bytes(len(data) - cut)):
                path.write_bytes(damaged)
                try:
                    images.heic_page_as_png(str(path), 1)
                    outcomes.add("picture")
                except ValueError as error:  # the only kind the route turns into a 422
                    assert "cannot be read" in str(error) or "has " in str(error)
                    outcomes.add("readable")
        assert "readable" in outcomes


class TestHeicPagesAreTheOnesTheAddOnReads:
    """The preview shows the picture that was read: its pages are the add-on's, one for one. This
    needs the HEIC add-on, so it is skipped without it."""

    def test_the_same_pictures_in_the_same_order(self, tmp_path):
        import io

        pillow_heif = pytest.importorskip("pillow_heif")
        from PIL import Image

        reader = pytest.importorskip("vethuq_addon_heic.reader")
        from vethuq_api import images

        def solid(colour):
            return Image.new("RGB", (60, 30), colour)

        cases = {
            "still": ([solid((9, 9, 9))], None),
            "three": ([solid((255, 0, 0)), solid((0, 255, 0)), solid((0, 0, 255))], 0),
            "primary": ([solid((255, 0, 0)), solid((0, 255, 0)), solid((0, 0, 255))], 1),
            "last": ([solid((n * 30, 0, 0)) for n in range(1, 6)], 4),
        }
        for name, (frames, primary) in cases.items():
            file = pillow_heif.HeifFile()
            for frame in frames:
                file.add_from_pillow(frame)
            path = tmp_path / f"{name}.heic"
            file.save(path, quality=90, primary_index=primary)
            read = [
                page.render(None)[:, :, ::-1].copy()  # BGR to RGB
                for page in reader.HeicReader().read(path)
            ]
            assert len(read) == len(frames), name
            for number, expected in enumerate(read, start=1):
                shown = Image.open(io.BytesIO(images.heic_page_as_png(str(path), number)))
                assert shown.convert("RGB").tobytes() == expected.tobytes(), (name, number)

    def test_the_limits_match(self):
        reader = pytest.importorskip("vethuq_addon_heic.reader")
        from vethuq_api import images

        assert images.HEIC_MAX_PAGES == reader.HeicReader.MAX_PAGES


class TestJp2Pictures:
    """A JPEG 2000 shown as a PNG (no browser but Safari draws it). The JPEG 2000 add-on may not be
    installed in this checkout, so the type check is replaced; the route and the picture are what is
    tested."""

    @pytest.fixture
    def http(self, web_dist, library, monkeypatch):
        from PIL import Image, ImageDraw

        folder = library / "a"
        red = Image.new("RGB", (40, 20), (255, 0, 0))
        red.save(folder / "red.jp2", "JPEG2000")
        ink = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
        ImageDraw.Draw(ink).rectangle([10, 10, 20, 20], fill=(0, 0, 0, 255))
        ink.save(folder / "transparent.jp2", "JPEG2000")
        Image.new("CMYK", (8, 8), (0, 0, 0, 0)).save(folder / "cmyk.jp2", "JPEG2000")
        red.save(folder / "raw.j2k", "JPEG2000", no_jp2=True)
        red.save(folder / "really.jp2", "PNG")  # another format under a .jp2 name
        (folder / "notes.jp2").write_bytes(b"this is not a picture")
        data = (folder / "red.jp2").read_bytes()
        (folder / "cut.jp2").write_bytes(data[: len(data) // 2])
        red.save(library / "outside.png", "PNG")
        monkeypatch.setattr(
            SearchService,
            "is_type",
            lambda self, path, wanted: wanted == "jp2" and path.lower().endswith((".jp2", ".j2k")),
        )
        real = SourcesService.may_open
        inside = os.path.realpath(folder)

        def may_open(self, path):
            real_path = os.path.realpath(path)
            return real(self, path) or (
                os.path.isfile(real_path) and real_path.startswith(inside + os.sep)
            )

        monkeypatch.setattr(SourcesService, "may_open", may_open)
        core = VethuQCore(library / "vethuq.db")
        core._vethuq().sources.create(folder)
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        test.library = library
        return test

    def get(self, http, name="red.jp2"):
        path = http.library / "a" / name
        return http.get("/api/files/jp2", query_string={"path": str(path)}, base_url=ORIGIN)

    def picture(self, reply):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(reply.data)).convert("RGB")

    def test_it_is_a_png_of_the_picture(self, http):
        reply = self.get(http)
        assert reply.status_code == 200 and reply.mimetype == "image/png"
        assert reply.headers["Content-Disposition"] == "inline"
        assert self.picture(reply).size == (40, 20)
        assert self.picture(reply).getpixel((0, 0)) == (255, 0, 0)

    def test_a_raw_codestream_is_shown_too(self, http):
        assert self.picture(self.get(http, "raw.j2k")).getpixel((0, 0)) == (255, 0, 0)

    def test_transparency_is_laid_on_white_so_ink_shows_on_any_theme(self, http):
        picture = self.picture(self.get(http, "transparent.jp2"))
        assert picture.getpixel((0, 0)) == (255, 255, 255)
        assert picture.getpixel((15, 15)) == (0, 0, 0)

    def test_a_cmyk_picture_is_shown(self, http):
        assert self.get(http, "cmyk.jp2").status_code == 200

    def test_only_a_jp2_of_a_source(self, http):
        outside = {"path": str(http.library / "outside.png")}
        assert http.get("/api/files/jp2", query_string=outside, base_url=ORIGIN).status_code == 422
        assert self.get(http, "missing.jp2").status_code == 422

    def test_damaged_files_say_so_and_never_give_a_server_error(self, http):
        for name in ("notes.jp2", "cut.jp2", "really.jp2"):
            reply = self.get(http, name)
            assert reply.status_code == 422, name
            assert "cannot be read" in reply.get_json()["error"], name
            assert "JPEG 2000" in reply.get_json()["error"], name

    def test_a_picture_that_is_too_large_is_refused(self, http, monkeypatch):
        monkeypatch.setattr("vethuq_api.images.MAX_PIXELS", 500)
        reply = self.get(http)  # 40 x 20 = 800 pixels
        assert reply.status_code == 422 and "too large to preview" in reply.get_json()["error"]

    def test_a_picture_pillow_only_warns_about_is_refused_too(self, http, monkeypatch):
        from PIL import Image

        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 500)  # 800 pixels: a warning, not an error
        reply = self.get(http)
        assert reply.status_code == 422 and "cannot be read" in reply.get_json()["error"]

    def test_every_cut_and_flip_is_a_picture_or_a_readable_error(self, tmp_path):
        from PIL import Image

        from vethuq_api import images

        source = tmp_path / "a.jp2"
        Image.effect_noise((100, 80), 80).convert("RGB").save(source, "JPEG2000")
        data = source.read_bytes()
        path = tmp_path / "damaged.jp2"
        outcomes = set()
        for at in range(0, len(data) - 1, max(1, len(data) // 200)):
            flipped = bytearray(data)
            flipped[at] ^= 0xFF
            for damaged in (data[:at], bytes(flipped)):
                path.write_bytes(damaged)
                try:
                    images.jp2_as_png(str(path))
                    outcomes.add("picture")
                except ValueError as error:  # the only kind the route turns into a 422
                    assert "cannot be read" in str(error)
                    outcomes.add("readable")
        assert "readable" in outcomes


class TestImageConverterNeverGivesAnUnhandledError:
    """Pillow's plugins raise all sorts of errors for a file cut off partway; the preview turns each
    into a readable message (it was an unhandled server error for some of them)."""

    @pytest.mark.parametrize("kind", ["GIF", "WEBP", "BMP", "TIFF"])
    def test_every_cut_is_either_a_picture_or_a_readable_error(self, tmp_path, kind):
        import io
        import warnings

        from PIL import Image, ImageDraw

        from vethuq_api import images

        def frame(n):
            image = Image.new("RGB", (24, 24), (n * 80, 10, 10))
            ImageDraw.Draw(image).rectangle([2 + n * 4, 2, 12 + n * 4, 12], fill=(255, 255, 255))
            return image

        out = io.BytesIO()
        frames = [frame(n) for n in range(3)]
        multi = kind in ("GIF", "WEBP", "TIFF")
        extra = {"lossless": True} if kind == "WEBP" else {}
        frames[0].save(
            out, kind, save_all=multi, append_images=frames[1:] if multi else [], **extra
        )
        data = out.getvalue()
        convert = {
            "GIF": images.gif_page_as_png,
            "WEBP": images.webp_page_as_png,
            "BMP": lambda path, page: images.bmp_as_png(path),
            "TIFF": images.tiff_frame_as_png,
        }[kind]
        path = tmp_path / f"cut.{kind.lower()}"
        outcomes = set()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Pillow warns about a truncated TIFF
            for cut in range(0, len(data) - 1, 1 if len(data) < 2000 else 5):
                path.write_bytes(data[:cut])
                try:
                    convert(str(path), 1)
                    outcomes.add("picture")
                except ValueError as error:  # the only kind the route turns into a 422
                    assert "cannot be read" in str(error) or "has " in str(error)
                    outcomes.add("readable")
        assert "readable" in outcomes


class TestWebpPagesAreTheOnesTheAddOnReads:
    """The preview shows the picture that was read: its pages are the add-on's, one for one. This
    needs the WebP add-on (installed with the image bundle), so it is skipped without it."""

    def test_the_same_number_of_pages_and_the_same_pictures(self, tmp_path):
        import io

        from PIL import Image, ImageDraw

        reader = pytest.importorskip("vethuq_addon_webp.reader")
        from vethuq_api import images

        def solid(colour):
            return Image.new("RGB", (60, 30), colour)

        base = solid((200, 200, 200))
        captioned = base.copy()
        ImageDraw.Draw(captioned).rectangle([40, 20, 50, 28], fill=(0, 0, 0))
        cases = {
            "still": [solid((9, 9, 9))],
            "loop": [solid((255, 0, 0)), solid((0, 255, 0))] * 4,
            "returns": [
                solid((255, 0, 0)),
                solid((0, 255, 0)),
                solid((255, 0, 0)),
                solid((0, 0, 255)),
            ],
            "partial": [base, captioned, base, captioned],
            "many": [solid((n * 7, 0, 0)) for n in range(1, 41)],  # more than the page limit
        }
        for name, frames in cases.items():
            path = tmp_path / f"{name}.webp"
            frames[0].save(
                path,
                "WEBP",
                save_all=len(frames) > 1,
                append_images=frames[1:],
                lossless=True,
                duration=50,
            )
            read = [
                page.render(None)[:, :, ::-1].copy()  # BGR to RGB
                for page in reader.WebpReader().read(path)
            ]
            assert images.animated_pages(str(path), "WEBP") == len(read), name
            for number, expected in enumerate(read, start=1):
                shown = Image.open(io.BytesIO(images.webp_page_as_png(str(path), number)))
                assert shown.convert("RGB").tobytes() == expected.tobytes(), (name, number)

    def test_the_limits_match(self):
        reader = pytest.importorskip("vethuq_addon_webp.reader")
        from vethuq_api import images

        assert images.ANIMATION_MAX_PAGES == reader.WebpReader.MAX_PAGES
        assert images.ANIMATION_MAX_SCAN_FRAMES == reader.WebpReader.MAX_SCAN_FRAMES
