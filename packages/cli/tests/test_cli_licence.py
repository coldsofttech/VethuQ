"""`vethuq licence`: install, show, code and request (with a stand-in for vethuq-entitlements)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

DEVICE = "d" * 64


def licence(*addons, status="ok"):
    return SimpleNamespace(
        ok=status == "ok",
        status=SimpleNamespace(value=status),
        detail="",
        licence_id="LIC-1",
        kind="addon",
        valid_until=datetime(2027, 1, 1, tzinfo=UTC),
        entitlements=[SimpleNamespace(addon_id=a) for a in addons],
    )


@pytest.fixture
def entitlements(monkeypatch):
    state = SimpleNamespace(licence=licence("csv", "txt", "gone"), codes=[])

    class Licences:
        def verify(self, token, revoked=(), github_owner_id=None):
            return state.licence

        @staticmethod
        def device_hash():
            return DEVICE

    class RequestCode:
        @staticmethod
        def encode(device, version, github=None, runner=None):
            state.codes.append((github, runner))
            return "VQREQ1.test"

    module = ModuleType("vethuq_entitlements")
    module.Licences, module.RequestCode = Licences, RequestCode
    monkeypatch.setitem(sys.modules, "vethuq_entitlements", module)
    return state


def test_install_stores_the_licence_on_every_listed_addon(run, entitlements):
    result = run("licence", "install", "VQLIC1.token")
    assert result.exit_code == 0, result.output
    assert "stored" in result.output and "not_installed" in result.output
    assert "Installed on 2 add-on(s)" in result.output and "gone" in result.output
    assert "LIC-1" in run("licence", "show").output


def test_install_from_a_file(run, entitlements, tmp_path):
    path = tmp_path / "acme.vqlic"
    path.write_text("VQLIC1.file\n")
    assert run("licence", "install", "--file", str(path)).exit_code == 0
    assert "unchanged" in run("licence", "install", "--file", str(path)).output


def test_install_needs_exactly_one_of_key_and_file(run, entitlements, tmp_path):
    assert run("licence", "install").exit_code != 0
    path = tmp_path / "a.vqlic"
    path.write_text("x")
    assert run("licence", "install", "VQLIC1.t", "--file", str(path)).exit_code != 0


def test_an_invalid_licence_is_an_error_and_stores_nothing(run, entitlements):
    entitlements.licence = licence("csv", status="expired")
    result = run("licence", "install", "VQLIC1.old")
    assert result.exit_code != 0 and "isn't valid" in str(result.exception)
    assert "No licence is installed" in run("licence", "show").output


def test_install_as_json(run_json, entitlements):
    rows = run_json("licence", "install", "VQLIC1.token")
    assert {r["addon_id"]: r["status"] for r in rows} == {
        "csv": "stored", "gone": "not_installed", "txt": "stored"
    }  # fmt: skip


def test_show_as_json(run, run_json, entitlements):
    run("licence", "install", "VQLIC1.token")
    (shown,) = run_json("licence", "show")
    assert shown["lists"] == ["csv", "gone", "txt"] and shown["installed_on"] == ["csv", "txt"]


def test_code_prints_the_request_code(run, entitlements):
    result = run("licence", "code", "--github-id", "42", "--runner-owner-id", "7")
    assert "VQREQ1.test" in result.output and entitlements.codes == [(42, 7)]


def test_request_shows_the_privacy_text_and_exactly_what_is_sent(run, entitlements):
    result = run("licence", "request", "--addon", "docx", "--bundle", "office", "--note", "hi")
    assert result.exit_code == 0, result.output
    assert "PUBLIC issue" in result.output and "request code" in result.output
    assert "docx, office" in result.output and "licence-request.yml" in result.output


def test_request_as_json_has_the_same_url(run, run_json, entitlements):
    data = run_json("licence", "request", "--type", "top-up", "--wallet", "local")
    query = parse_qs(urlparse(data["url"]).query)
    assert query["template"] == ["topup-request.yml"] and query["wallet"] == ["local"]
    assert set(data["fields"]) == {"request_code", "wallet"}


def test_request_opens_the_browser_only_when_asked_and_confirmed(run, entitlements, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "vethuq_cli.licence.webbrowser.open", lambda url: opened.append(url) or True
    )
    run("licence", "request", "--addon", "docx")
    assert opened == []
    from typer.testing import CliRunner
    from vethuq_cli.main import build_app

    declined = CliRunner().invoke(
        build_app(), ["licence", "request", "--addon", "docx", "--open"], input="n\n"
    )
    assert opened == [] and "Open this in your browser?" in declined.output
    assert run("licence", "request", "--addon", "docx", "--open", "--yes").exit_code == 0
    assert len(opened) == 1 and opened[0].startswith(
        "https://github.com/coldsofttech/VethuQ/issues/new"
    )


def test_a_bad_request_is_refused_before_anything_opens(run, entitlements, monkeypatch):
    opened = []
    monkeypatch.setattr("vethuq_cli.licence.webbrowser.open", lambda url: opened.append(url))
    result = run("licence", "request", "--addon", "../etc", "--open", "--yes")
    assert result.exit_code != 0 and opened == []


def test_the_licence_group_is_in_the_help(run, entitlements):
    assert "licence" in run("--help").output
