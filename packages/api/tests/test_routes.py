from __future__ import annotations

from api_support import ORIGIN

from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore


class TestPlatform:
    def test_desktop_host_with_window(self, signed_in):
        body = signed_in.get("/api/platform", base_url=ORIGIN).get_json()
        assert body == {"kind": "desktop", "window_controls": True}

    def test_web_host_has_no_window_controls_or_window_routes(self, web_dist):
        app = create_app(bootstrap_token="t", web_dist=web_dist)
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        assert client.get("/api/platform", base_url=ORIGIN).get_json() == {
            "kind": "web",
            "window_controls": False,
        }
        assert client.get("/api/window/state", base_url=ORIGIN).status_code == 404


class TestWindow:
    def test_state_follows_the_window(self, signed_in, window):
        assert signed_in.get("/api/window/state", base_url=ORIGIN).get_json() == {
            "maximized": False
        }
        headers = {"Origin": ORIGIN}
        assert signed_in.post(
            "/api/window/maximize", base_url=ORIGIN, headers=headers
        ).get_json() == {"maximized": True}
        assert signed_in.post(
            "/api/window/restore", base_url=ORIGIN, headers=headers
        ).get_json() == {"maximized": False}
        signed_in.post("/api/window/minimize", base_url=ORIGIN, headers=headers)
        signed_in.post("/api/window/close", base_url=ORIGIN, headers=headers)
        assert window.calls == ["maximize", "restore", "minimize", "close"]


class TestAbout:
    def test_reports_the_installation_through_the_core(self, web_dist):
        app = create_app(bootstrap_token="t", web_dist=web_dist)
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        body = client.get("/api/about", base_url=ORIGIN).get_json()
        assert set(body) >= {"vethuq", "python", "platform", "db_schema"}


class TestCatalog:
    def test_lists_what_the_core_reports(self, signed_in):
        body = signed_in.get("/api/catalog", base_url=ORIGIN).get_json()
        assert body["add_ons"][0]["id"] == "csv"

    def test_needs_a_session(self, client):
        assert client.get("/api/catalog", base_url=ORIGIN).status_code == 401

    def test_real_core_reports_every_catalog(self, web_dist, tmp_path):
        app = create_app(
            bootstrap_token="t", web_dist=web_dist, core=VethuQCore(tmp_path / "vethuq.db")
        )
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        body = client.get("/api/catalog", base_url=ORIGIN).get_json()
        assert set(body) == {"add_ons", "file_types", "search_engines", "languages", "ocr_engines"}
        assert all(isinstance(rows, list) for rows in body.values())


class TestBrand:
    def test_needs_a_session(self, client):
        assert client.get("/api/brand", base_url=ORIGIN).status_code == 401

    def test_real_core_reports_name_tagline_and_both_palettes(self, web_dist, tmp_path):
        app = create_app(
            bootstrap_token="t", web_dist=web_dist, core=VethuQCore(tmp_path / "vethuq.db")
        )
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        body = client.get("/api/brand", base_url=ORIGIN).get_json()
        assert body["name"] == "VethuQ"
        assert body["tagline"]
        for scheme in ("light", "dark"):
            assert body["palette"][scheme]["primary"].startswith("#")
        assert body["palette"]["light"].keys() == body["palette"]["dark"].keys()
