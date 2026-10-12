from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from vethuq_api import create_app
from vethuq_desktop.server import HOST, LocalServer
from vethuq_desktop.webdist import WebDistNotFoundError, resolve_web_dist


@pytest.fixture
def server(tmp_path):
    (tmp_path / "index.html").write_text("<title>VethuQ</title>")
    app = create_app(bootstrap_token="token", web_dist=tmp_path)
    local = LocalServer(app)
    local.start()
    local.wait_until_ready()
    yield local
    local.stop()


def test_binds_to_loopback_on_a_free_port(server):
    assert server.port > 0
    assert server._server.server_address[0] == HOST


def test_two_servers_get_different_ports(tmp_path):
    first = LocalServer(create_app(bootstrap_token="a"))
    second = LocalServer(create_app(bootstrap_token="b"))
    try:
        assert first.port != second.port
    finally:
        first._server.server_close()
        second._server.server_close()


def test_answers_health_over_http(server):
    with urllib.request.urlopen(f"{server.origin}/api/health", timeout=2) as response:  # noqa: S310
        assert json.load(response) == {"status": "ok"}


def test_refuses_a_request_for_another_host_name(server):
    url = f"{server.origin}/api/health"
    request = urllib.request.Request(url, headers={"Host": "evil.example"})  # noqa: S310
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=2)  # noqa: S310
    assert caught.value.code == 403


def test_stop_releases_the_port(server):
    server.stop()
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(f"{server.origin}/api/health", timeout=1)  # noqa: S310


class TestWebDist:
    def test_explicit_path_wins(self, tmp_path):
        (tmp_path / "index.html").write_text("x")
        assert resolve_web_dist(tmp_path) == tmp_path

    def test_environment_variable(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("x")
        monkeypatch.setenv("VETHUQ_WEB_DIST", str(tmp_path))
        assert resolve_web_dist() == tmp_path

    def test_missing_build_explains_what_to_do(self, tmp_path):
        with pytest.raises(WebDistNotFoundError, match="npm run build"):
            resolve_web_dist(tmp_path / "nothing")
