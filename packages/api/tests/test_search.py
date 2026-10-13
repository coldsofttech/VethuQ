from __future__ import annotations

import os

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
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
            spec = probe.file_types.get(kind)
            installed = spec is not None and spec.available
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
            spec = probe.file_types.get(kind)
            installed = spec is not None and spec.available
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
