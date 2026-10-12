from __future__ import annotations

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
