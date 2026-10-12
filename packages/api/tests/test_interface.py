from __future__ import annotations

from api_support import ORIGIN, TOKEN

from vethuq_api import allow_host, create_app


def test_serves_index_at_the_root(signed_in):
    response = signed_in.get("/", base_url=ORIGIN)
    assert response.status_code == 200
    assert b"<title>VethuQ</title>" in response.data
    assert response.headers["Cache-Control"] == "no-cache"


def test_serves_assets_with_long_caching(signed_in):
    response = signed_in.get("/assets/app.js", base_url=ORIGIN)
    assert response.status_code == 200
    assert "immutable" in response.headers["Cache-Control"]


def test_unknown_route_falls_back_to_the_interface(signed_in):
    assert b"<title>VethuQ</title>" in signed_in.get("/some/page", base_url=ORIGIN).data


def test_missing_file_is_a_404_not_the_interface(signed_in):
    assert signed_in.get("/assets/missing.js", base_url=ORIGIN).status_code == 404


def test_cannot_read_files_outside_the_interface(signed_in):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        response = signed_in.get(path, base_url=ORIGIN)
        assert b"outside the interface" not in response.data


def test_reports_when_the_interface_is_not_built(tmp_path):
    app = create_app(bootstrap_token=TOKEN, web_dist=tmp_path / "missing")
    allow_host(app, "127.0.0.1:5000")
    assert app.test_client().get("/", base_url=ORIGIN).status_code == 503
