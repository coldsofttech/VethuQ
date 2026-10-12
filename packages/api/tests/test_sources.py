from __future__ import annotations

import json

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.sources_service import SourcesService

HEADERS = {"Origin": ORIGIN}


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("alpha")
    (root / "b.csv").write_text("x,y\n1,2\n")
    (root / "sub" / "d.md").write_text("# beta")
    (root / "c.xyz").write_text("binary")
    (tmp_path / "single.txt").write_text("one file")
    return tmp_path


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


@pytest.fixture
def service(vethuq):
    return SourcesService(lambda: vethuq)


class TestSources:
    def test_a_folder_and_a_file_are_added_with_their_type(self, service, library):
        folder = service.add(str(library / "library"))
        single = service.add(str(library / "single.txt"))
        assert (folder["type"], folder["name"]) == ("folder", "library")
        assert (single["type"], single["name"]) == ("file", "single.txt")
        assert folder["missing"] is False
        assert folder["languages"] is None  # the default languages apply
        assert {s["name"] for s in service.list()} == {"library", "single.txt"}

    def test_listing_filters_sorts_and_searches(self, service, library):
        service.add(str(library / "library"))
        service.add(str(library / "single.txt"))
        assert [s["name"] for s in service.list(source_type="file")] == ["single.txt"]
        assert [s["name"] for s in service.list(q="LIBRARY")] == ["library"]
        assert [s["name"] for s in service.list(sort="path", order="desc")] == [
            "single.txt",
            "library",
        ]
        assert service.list(status="completed") == []

    def test_removed_sources_are_hidden_until_asked_for_and_can_be_restored(self, service, library):
        added = service.add(str(library / "single.txt"))
        removed = service.remove(added["id"])
        assert removed["status"] == "removed"
        assert service.list() == []
        assert [s["id"] for s in service.list(removed=True)] == [added["id"]]
        restored = service.restore(added["id"])
        assert restored["status"] != "removed"
        assert [s["id"] for s in service.list()] == [added["id"]]

    def test_a_removed_source_can_be_purged_but_an_active_one_cannot(self, service, library):
        from vethuq.errors import SourceNotRemovedError

        added = service.add(str(library / "single.txt"))
        with pytest.raises(SourceNotRemovedError):
            service.purge(added["id"])
        service.remove(added["id"])
        assert service.purge(added["id"])["id"] == added["id"]
        assert service.list(removed=True) == []

    def test_languages_can_be_set_and_cleared(self, service, library):
        added = service.add(str(library / "single.txt"))
        assert service.set_languages(added["id"], ["en"])["languages"] == ["en"]
        assert service.set_languages(added["id"], [])["languages"] is None

    def test_a_missing_path_is_flagged(self, service, library):
        added = service.add(str(library / "single.txt"))
        (library / "single.txt").unlink()
        assert service.get(added["id"])["missing"] is True


class TestFiles:
    @pytest.fixture
    def source(self, service, library):
        return service.add(str(library / "library"))["id"]

    def test_every_file_is_listed_with_its_type_and_status(self, service, source):
        page = service.files(source)
        rows = {f["relative_path"]: f for f in page["items"]}
        assert set(rows) == {"a.txt", "b.csv", "c.xyz", "sub/d.md"}
        assert (rows["a.txt"]["file_type"], rows["a.txt"]["status"]) == ("txt", "pending")
        assert (rows["c.xyz"]["file_type"], rows["c.xyz"]["status"]) == (None, "unsupported")
        assert rows["c.xyz"]["protected"] is False
        assert page["total"] == page["all"] == 4

    def test_facets_count_the_statuses_and_types(self, service, source):
        facets = service.files(source)["facets"]
        assert facets["status"] == {"pending": 3, "unsupported": 1}
        assert facets["type"]["unsupported"] == 1
        assert facets["type"]["txt"] == 1

    def test_filters(self, service, source):
        assert service.files(source, status="unsupported")["total"] == 1
        assert [f["name"] for f in service.files(source, file_type="csv")["items"]] == ["b.csv"]
        assert [f["name"] for f in service.files(source, file_type="unsupported")["items"]] == [
            "c.xyz"
        ]
        assert [f["name"] for f in service.files(source, q="SUB")["items"]] == ["d.md"]
        assert service.files(source, band="high")["total"] == 0
        assert service.files(source, min_confidence=0.5)["total"] == 0

    def test_sorting_and_paging(self, service, source):
        by_size = [f["name"] for f in service.files(source, sort="size", order="desc")["items"]]
        assert by_size[0] == "b.csv"
        names = [f["name"] for f in service.files(source, sort="name")["items"]]
        assert names == sorted(names, key=str.casefold)
        page = service.files(source, sort="name", offset=1, limit=2)
        assert [f["name"] for f in page["items"]] == names[1:3]
        assert page["total"] == 4

    def test_a_bad_sort_or_order_is_refused(self, service, source):
        with pytest.raises(ValueError, match="sort"):
            service.files(source, sort="nope")
        with pytest.raises(ValueError, match="order"):
            service.files(source, order="sideways")

    def test_the_scan_is_kept_until_asked_again(self, service, source, library):
        assert service.files(source)["all"] == 4
        (library / "library" / "new.txt").write_text("new")
        assert service.files(source)["all"] == 4  # kept
        assert service.files(source, refresh=True)["all"] == 5
        service.forget(source)
        (library / "library" / "newer.txt").write_text("newer")
        assert service.files(source)["all"] == 6

    def test_a_file_that_needs_a_password_is_marked_protected(self):
        from types import SimpleNamespace

        from vethuq.enums import FileStatus
        from vethuq_api.sources_service import file_dict

        index = SimpleNamespace(
            status=FileStatus.UNSUPPORTED,
            file_type="pdf",
            error="needs a password",
            sha256=None,
            indexed_at=None,
            retry_count=0,
            duplicate_of=None,
            pages=None,
            confidence=None,
            languages=None,
            low_confidence_pages=None,
            band=None,
            on_disk=True,
        )
        item = SimpleNamespace(
            path="/x/a.pdf",
            relative_path="a.pdf",
            name="a.pdf",
            size_bytes=1,
            modified_at="2026-01-01T00:00:00Z",
            index=index,
        )
        assert file_dict(item)["protected"] is True


class TestExport:
    def test_sources_export_as_json_and_html(self, service, library):
        service.add(str(library / "library"))
        data, name, mime = service.export_sources("json")
        assert (name, mime) == ("sources.json", "application/json")
        assert "library" in json.dumps(json.loads(data))
        data, name, mime = service.export_sources("html")
        assert name == "sources.html" and b"<html" in data.lower()

    def test_the_files_exported_are_the_ones_filtered(self, service, library):
        source = service.add(str(library / "library"))["id"]
        data, name, _ = service.export_files(source, "json", file_type="csv")
        text = data.decode()
        assert "b.csv" in text and "a.txt" not in text
        assert name == f"files-of-{source}.json"

    def test_an_unknown_format_is_refused(self, service, library):
        service.add(str(library / "library"))
        with pytest.raises(ValueError, match="json or html"):
            service.export_sources("pdf")


class TestHttp:
    @pytest.fixture
    def http(self, web_dist, tmp_path):
        app = create_app(
            bootstrap_token="t", web_dist=web_dist, core=VethuQCore(tmp_path / "vethuq.db")
        )
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        return client

    def post(self, http, url, **body):
        return http.post(f"/api{url}", json=body, base_url=ORIGIN, headers=HEADERS)

    def test_add_list_files_and_remove_over_http(self, http, library):
        created = self.post(http, "/sources", path=str(library / "library"))
        assert created.status_code == 201
        source_id = created.get_json()["id"]

        listing = http.get("/api/sources", base_url=ORIGIN).get_json()
        assert [s["id"] for s in listing["sources"]] == [source_id]

        files = http.get(
            f"/api/sources/{source_id}/files?sort=size&order=desc&limit=2", base_url=ORIGIN
        ).get_json()
        assert files["total"] == 4 and len(files["items"]) == 2

        removed = http.delete(f"/api/sources/{source_id}", base_url=ORIGIN, headers=HEADERS)
        assert removed.get_json()["status"] == "removed"
        assert self.post(http, f"/sources/{source_id}/restore").status_code == 200

    def test_errors_become_the_right_status_with_the_reason(self, http, library):
        assert self.post(http, "/sources", path=str(library / "nope")).status_code == 422
        self.post(http, "/sources", path=str(library / "single.txt"))
        assert self.post(http, "/sources", path=str(library / "single.txt")).status_code == 409
        assert http.get("/api/sources/999", base_url=ORIGIN).status_code == 404
        assert self.post(http, "/sources", path="").status_code == 422
        assert self.post(http, "/sources/1/purge").status_code == 409  # still active
        bad = http.get("/api/sources/1/files?sort=nope", base_url=ORIGIN)
        assert bad.status_code == 422

    def test_exports_download_as_attachments(self, http, library):
        self.post(http, "/sources", path=str(library / "library"))
        response = http.get("/api/sources/export?format=html", base_url=ORIGIN)
        assert response.status_code == 200
        assert "attachment" in response.headers["Content-Disposition"]
        files = http.get("/api/sources/1/files/export?format=json&type=csv", base_url=ORIGIN)
        assert b"b.csv" in files.data

    def test_changes_need_the_app_origin(self, http, library):
        response = http.post("/api/sources", json={"path": str(library)}, base_url=ORIGIN)
        assert response.status_code == 403
