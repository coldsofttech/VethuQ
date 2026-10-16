"""`client.licences`: installing one licence on every add-on it lists, and asking for a licence."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

import vethuq
from vethuq import errors
from vethuq.licences import REQUEST_FIELDS, REQUEST_PRIVACY, Licences

DEVICE = "d" * 64


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


def fake_bundle(bundle_id, active=True):
    return SimpleNamespace(bundle_id=bundle_id, expires=None, is_active=lambda now: active)


def fake_licence(*addons, status="ok", licence_id="LIC-1", kind="addon", detail="", bundles=()):
    return SimpleNamespace(
        bundles=[fake_bundle(b) if isinstance(b, str) else b for b in bundles],
        ok=status == "ok",
        status=SimpleNamespace(value=status),
        detail=detail,
        licence_id=licence_id,
        kind=kind,
        valid_until=datetime(2027, 1, 1, tzinfo=UTC),
        entitlements=[SimpleNamespace(addon_id=a) for a in addons],
    )


@pytest.fixture
def entitlements(monkeypatch):
    """A stand-in for `vethuq-entitlements`: `seen` records how it was called."""
    state = SimpleNamespace(licence=fake_licence("csv", "txt"), seen=[], codes=[])

    class FakeLicences:
        def verify(self, token, revoked=(), github_owner_id=None):
            state.seen.append((token, sorted(revoked), github_owner_id))
            return state.licence

        @staticmethod
        def device_hash():
            return DEVICE

    class FakeRequestCode:
        @staticmethod
        def encode(device, version, github=None, runner=None):
            state.codes.append((device, version, github, runner))
            return f"VQREQ1.{device[:4]}.{github}.{runner}"

    module = ModuleType("vethuq_entitlements")
    module.Licences, module.RequestCode = FakeLicences, FakeRequestCode
    monkeypatch.setitem(sys.modules, "vethuq_entitlements", module)
    return state


def stored(client, addon_id):
    return client.addons.settings(addon_id).get("licence")


class TestInstall:
    def test_one_paste_stores_the_token_on_every_installed_addon_it_lists(
        self, client, entitlements
    ):
        entitlements.licence = fake_licence("csv", "txt", "no-such-addon")
        results = {r.addon_id: r.status for r in client.licences.install(" VQLIC1.a b\n.c ")}
        assert results == {"csv": "stored", "no-such-addon": "not_installed", "txt": "stored"}
        assert stored(client, "csv") == stored(client, "txt") == "VQLIC1.ab.c"
        assert stored(client, "pdf") is None

    def test_installing_again_changes_nothing_and_a_new_token_replaces(self, client, entitlements):
        client.licences.install("VQLIC1.one")
        assert {r.status for r in client.licences.install("VQLIC1.one")} == {"unchanged"}
        assert {r.status for r in client.licences.install("VQLIC1.two")} == {"replaced"}
        assert stored(client, "csv") == "VQLIC1.two"

    def test_an_invalid_licence_stores_nothing(self, client, entitlements):
        entitlements.licence = fake_licence("csv", status="expired", detail="expired on 2025-01-01")
        with pytest.raises(errors.InvalidLicenceError, match="expired on 2025-01-01"):
            client.licences.install("VQLIC1.old")
        assert stored(client, "csv") is None

    def test_a_licence_that_lists_nothing_is_refused_with_a_hint(self, client, entitlements):
        entitlements.licence = fake_licence(kind="topup")
        with pytest.raises(errors.InvalidLicenceError, match="doesn't unlock any add-on") as stop:
            client.licences.install("VQLIC1.credits")
        assert "redeem_licence" in str(stop.value)

    @pytest.mark.parametrize("text", ["", "   \n", "x" * 20000])
    def test_nothing_or_too_much_is_not_a_licence(self, client, entitlements, text):
        with pytest.raises(errors.InvalidLicenceError):
            client.licences.install(text)

    def test_revoked_ids_from_the_policy_reach_the_check(self, client, entitlements, monkeypatch):
        monkeypatch.setattr(Licences, "_revoked", lambda self: frozenset({"OLD", "key-1"}))
        client.licences.install("VQLIC1.t")
        assert entitlements.seen[-1] == ("VQLIC1.t", ["OLD", "key-1"], None)

    def test_the_github_id_is_passed_to_the_check(self, client, entitlements):
        client.licences.install("VQLIC1.t", github_owner_id=4242)
        assert entitlements.seen[-1][2] == 4242

    def test_without_entitlements_it_says_so(self, client, monkeypatch):
        monkeypatch.setitem(sys.modules, "vethuq_entitlements", None)
        with pytest.raises(errors.InvalidLicenceError, match="vethuq-entitlements"):
            client.licences.install("VQLIC1.t")

    def test_the_addons_facade_does_the_same(self, client, entitlements):
        results = client.addons.install_licence("VQLIC1.t")
        assert {r.addon_id for r in results} == {"csv", "txt"} and stored(client, "txt")

    def test_install_results_serialise(self, client, entitlements):
        assert client.licences.install("VQLIC1.t")[0].to_dict() == {
            "addon_id": "csv",
            "status": "stored",
            "detail": "",
        }


class TestFile:
    def test_a_vqlic_file_is_installed(self, client, entitlements, tmp_path):
        path = tmp_path / "acme.vqlic"
        path.write_text("﻿VQLIC1.file\n", encoding="utf-8")
        assert {r.status for r in client.licences.install_file(path)} == {"stored"}
        assert stored(client, "csv") == "VQLIC1.file"

    def test_a_missing_binary_or_huge_file(self, client, entitlements, tmp_path):
        with pytest.raises(errors.InvalidLicenceError, match="can't be read"):
            client.licences.install_file(tmp_path / "none.vqlic")
        binary = tmp_path / "b.vqlic"
        binary.write_bytes(b"\xff\xfe\x00\x80")
        with pytest.raises(errors.InvalidLicenceError, match="isn't a licence file"):
            client.licences.install_file(binary)
        huge = tmp_path / "h.vqlic"
        huge.write_text("x" * 20000)
        with pytest.raises(errors.InvalidLicenceError, match="too large"):
            client.licences.install_file(huge)


class TestShow:
    def test_installed_licences_are_grouped_by_token(self, client, entitlements):
        client.licences.install("VQLIC1.t")
        (shown,) = client.licences.show()
        assert (
            shown.licence_id == "LIC-1"
            and shown.status == "ok"
            and shown.valid_until == "2027-01-01"
        )
        assert shown.lists == ("csv", "txt") and shown.installed_on == ("csv", "txt")
        assert shown.to_dict()["installed_on"] == ["csv", "txt"]

    def test_a_licence_that_no_longer_verifies_is_shown_with_its_status(self, client, entitlements):
        client.licences.install("VQLIC1.t")
        entitlements.licence = fake_licence("csv", "txt", status="revoked", detail="revoked")
        assert client.licences.show()[0].status == "revoked"

    def test_nothing_installed(self, client, entitlements):
        assert client.licences.show() == []


class TestRequestCode:
    def test_the_code_holds_the_device_and_version_only_by_default(self, client, entitlements):
        code = client.licences.request_code()
        assert code.startswith("VQREQ1.dddd") and entitlements.codes == [
            (DEVICE, vethuq.APP_VERSION, None, None)
        ]
        assert client.licences.device_hash() == DEVICE

    def test_a_given_github_id_is_used_and_remembered_for_the_licence_check(
        self, client, entitlements
    ):
        client.licences.request_code(github_owner_id=4242, runner_owner_id=777)
        assert entitlements.codes[-1][2:] == (4242, 777)
        assert client.licences.saved_github_id() == 4242
        client.licences.install("VQLIC1.t")
        assert entitlements.seen[-1][2] == 4242

    def test_nothing_is_remembered_without_asking_for_the_id(self, client, entitlements):
        client.licences.request_code()
        assert client.licences.saved_github_id() is None


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestGitHubId:
    def licences(self, client, answer, calls):
        def urlopen(request, timeout=0):
            calls.append((request.full_url, dict(request.header_items())))
            if isinstance(answer, Exception):
                raise answer
            return Reply(json.dumps(answer).encode())

        return Licences(client.addons, client.db_path, client._open_database, urlopen)

    def test_the_tokens_own_id_is_asked_from_the_user_endpoint(
        self, client, entitlements, monkeypatch
    ):
        monkeypatch.setenv("VETHUQ_GITHUB_TOKEN", "ghp_secret")
        calls = []
        desk = self.licences(client, {"id": 4242, "login": "someone", "email": "a@b.c"}, calls)
        assert desk.github_id() == 4242
        url, headers = calls[0]
        assert (
            url == "https://api.github.com/user" and headers["Authorization"] == "Bearer ghp_secret"
        )

    def test_an_owner_is_looked_up_by_name(self, client, entitlements, monkeypatch):
        for name in ("VETHUQ_GITHUB_TOKEN", "GITHUB_TOKEN"):
            monkeypatch.delenv(name, raising=False)
        calls = []
        assert self.licences(client, {"id": 99}, calls).github_id("acme-org") == 99
        assert calls[0][0] == "https://api.github.com/users/acme-org"
        assert "Authorization" not in calls[0][1]

    def test_the_token_never_goes_into_the_code(self, client, entitlements, monkeypatch):
        monkeypatch.setenv("VETHUQ_GITHUB_TOKEN", "ghp_secret")
        desk = self.licences(client, {"id": 4242, "login": "someone"}, [])
        code = desk.request_code(github=True)
        assert "ghp_secret" not in code and entitlements.codes[-1][2] == 4242

    def test_no_token_no_lookup(self, client, entitlements, monkeypatch):
        for name in ("VETHUQ_GITHUB_TOKEN", "GITHUB_TOKEN"):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(errors.LicenceRequestError, match="token is needed"):
            self.licences(client, {"id": 1}, []).github_id()
        with pytest.raises(errors.LicenceRequestError):
            client.licences.request_code(github=True)

    @pytest.mark.parametrize(
        "answer, text",
        [
            (urllib.error.HTTPError("u", 401, "no", {}, None), "refused the lookup \\(401\\)"),
            (OSError("down"), "can't be reached"),
            ({"login": "x"}, "no id"),
            ({"id": "7"}, "no id"),
        ],
    )
    def test_failures_are_clear(self, client, entitlements, monkeypatch, answer, text):
        monkeypatch.setenv("VETHUQ_GITHUB_TOKEN", "t")
        with pytest.raises(errors.LicenceRequestError, match=text):
            self.licences(client, answer, []).github_id()

    def test_a_bad_owner_name_is_refused_before_any_request(self, client, entitlements):
        calls = []
        with pytest.raises(errors.LicenceRequestError):
            self.licences(client, {"id": 1}, calls).github_id("../etc/passwd")
        assert calls == []


class TestRequestUrl:
    def query(self, request):
        parsed = urlparse(request.url)
        assert (parsed.scheme, parsed.netloc, parsed.path) == (
            "https", "github.com", "/coldsofttech/VethuQ/issues/new"
        )  # fmt: skip
        return {k: v[0] for k, v in parse_qs(parsed.query).items()}

    def test_a_licence_request(self, client, entitlements):
        request = client.licences.request(
            addons=["docx", "doc"], bundle="office", note="for my team"
        )
        query = self.query(request)
        assert query["template"] == "licence-request.yml" and query["title"] == "Licence request"
        assert query["request_code"] == request.code and query["addons"] == "docx, doc, office"
        assert query["note"] == "for my team" and request.fields["addons"] == "docx, doc, office"
        assert request.privacy == REQUEST_PRIVACY and "PUBLIC" in request.privacy

    @pytest.mark.parametrize(
        "kind, template", [("top-up", "topup-request.yml"), ("rebind", "rebind-request.yml")]
    )
    def test_the_other_kinds_use_their_forms(self, client, entitlements, kind, template):
        assert (
            self.query(client.licences.request(kind=kind, wallet="local"))["template"] == template
        )

    def test_only_the_allowed_fields_can_reach_the_url(self, client, entitlements):
        request = client.licences.request(
            addons=["docx"], wallet="semantic", note="hello", github_owner_id=4242
        )
        assert set(request.fields) <= set(REQUEST_FIELDS)
        assert set(self.query(request)) <= {"template", "title", *REQUEST_FIELDS}

    def test_nothing_else_is_in_the_url(self, client, entitlements, tmp_path):
        (tmp_path / "secret.txt").write_text("x")
        client.sources.create(tmp_path)
        url = client.licences.request(addons=["docx"]).url
        assert str(tmp_path) not in url and "secret" not in url and "VQLIC1" not in url

    def test_the_note_is_cleaned_and_cut(self, client, entitlements):
        request = client.licences.request(note="a\n\tb\x00c " + "z" * 500)
        assert "\n" not in request.fields["note"] and len(request.fields["note"]) <= 200
        assert (
            "\x00" not in request.url
            and self.query(client.licences.request(note="  "))["request_code"]
        )
        assert "note" not in client.licences.request(note="  ").fields

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"kind": "buy"},
            {"addons": ["../secret"]},
            {"addons": ["Docx"]},
            {"bundle": "a b"},
            {"wallet": "../x"},
        ],
    )
    def test_bad_fields_are_refused(self, client, entitlements, kwargs):
        with pytest.raises(errors.LicenceRequestError):
            client.licences.request(**kwargs)

    def test_a_code_made_earlier_is_used(self, client, entitlements):
        request = client.licences.request(code="VQREQ1.mine")
        assert request.code == "VQREQ1.mine" and entitlements.codes == []

    def test_to_dict(self, client, entitlements):
        data = client.licences.request(addons=["docx"]).to_dict()
        assert set(data) == {"kind", "code", "url", "fields", "privacy"}


def test_a_request_code_made_here_is_read_by_the_real_entitlements_package(client):
    entitlements = pytest.importorskip("vethuq_entitlements")
    if not hasattr(entitlements, "RequestCode"):
        pytest.skip("an older vethuq-entitlements without request codes")
    request = client.licences.request(addons=["docx"], github_owner_id=12345, runner_owner_id=678)
    info = entitlements.RequestCode.decode(request.code)
    assert (info.github_owner_id, info.runner_owner_id) == (12345, 678)
    assert (
        info.device_hash == client.licences.device_hash() and info.app_version == vethuq.APP_VERSION
    )


class TestBundleLicences:
    """One key for a bundle: stored on every add-on that says it is in the bundle."""

    @pytest.fixture(autouse=True)
    def declared(self, monkeypatch):
        from vethuq.addons.manage import Addons

        monkeypatch.setattr(
            Addons,
            "licence_bundles",
            lambda self: {"csv": ("office",), "txt": ("office", "email"), "pdf": ("web",)},
        )

    def test_a_bundle_licence_is_stored_on_the_addons_in_the_bundle_only(
        self, client, entitlements
    ):
        entitlements.licence = fake_licence(bundles=["office"])
        results = {r.addon_id: (r.status, r.detail) for r in client.licences.install("VQLIC1.b")}
        assert results == {
            "csv": ("stored", "through the office bundle"),
            "txt": ("stored", "through the office bundle"),
        }
        assert stored(client, "csv") == stored(client, "txt") == "VQLIC1.b"
        assert stored(client, "pdf") is None

    def test_an_addon_in_two_bundles_gets_the_licence_of_either(self, client, entitlements):
        entitlements.licence = fake_licence(bundles=["email"])
        assert {r.addon_id for r in client.licences.install("VQLIC1.e")} == {"txt"}

    def test_listed_addons_and_bundle_members_are_both_reached(self, client, entitlements):
        entitlements.licence = fake_licence("pdf", bundles=["email"])
        results = {r.addon_id: r.detail for r in client.licences.install("VQLIC1.x")}
        assert results == {"pdf": "", "txt": "through the email bundle"}

    def test_a_bundle_the_installed_addons_do_not_know_is_reported(self, client, entitlements):
        entitlements.licence = fake_licence("csv", bundles=["mystery"])
        results = {r.addon_id: r.status for r in client.licences.install("VQLIC1.m")}
        assert results == {"csv": "stored", "mystery": "unknown_bundle"}

    def test_an_ended_bundle_is_reported_and_stores_nothing_through_it(self, client, entitlements):
        entitlements.licence = fake_licence("pdf", bundles=[fake_bundle("office", active=False)])
        results = {r.addon_id: r.status for r in client.licences.install("VQLIC1.old")}
        assert results == {"office": "expired", "pdf": "stored"}
        assert stored(client, "csv") is None

    def test_a_licence_whose_only_bundle_cannot_be_used_is_refused(self, client, entitlements):
        entitlements.licence = fake_licence(bundles=["mystery"])
        with pytest.raises(errors.InvalidLicenceError, match="No add-on can be unlocked") as stop:
            client.licences.install("VQLIC1.m")
        assert "mystery" in str(stop.value)
        assert stored(client, "csv") is None

    def test_show_lists_the_bundle_and_the_addons_it_covers(self, client, entitlements):
        entitlements.licence = fake_licence(bundles=["office"])
        client.licences.install("VQLIC1.b")
        (shown,) = client.licences.show()
        assert shown.bundles == ("office",) and shown.lists == ("csv", "txt")
        assert shown.to_dict()["bundles"] == ["office"]

    def test_the_bundle_states(self, client, entitlements, monkeypatch):
        states = {b.bundle_id: b for b in client.licences.bundles()}
        assert set(states) == {"office", "email", "web"}
        assert {b.state for b in states.values()} == {"not_licensed"}
        assert states["office"].licensed_addons == ("csv", "txt")
        entitlements.licence = fake_licence(bundles=["office"])
        client.licences.install("VQLIC1.b")
        states = {b.bundle_id: b for b in client.licences.bundles()}
        assert states["office"].state == "licensed" and states["office"].licence_id == "LIC-1"
        assert states["office"].valid_until == "2027-01-01"
        # the email bundle here is just `txt`, which the office licence also covers; web is not
        assert states["email"].state == "licensed" and states["web"].state == "not_licensed"
        entitlements.licence = fake_licence(bundles=["office"], status="expired", detail="expired")
        assert {b.bundle_id: b.state for b in client.licences.bundles()}["office"] == "expired"

    def test_a_bundle_with_nothing_licensed_in_it_is_free(self, client, entitlements, monkeypatch):
        from vethuq.addons.manage import Addons

        monkeypatch.setattr(Addons, "licence_bundles", lambda self: {})
        monkeypatch.setattr(
            Addons,
            "bundles",
            lambda self, language=None: [
                SimpleNamespace(id="images", addons=("png", "jpg")),
            ],
        )
        assert [(b.bundle_id, b.state) for b in client.licences.bundles()] == [("images", "free")]

    def test_the_addons_facade_reports_what_running_addons_declare(self, client):
        assert client.addons.licence_bundles()["txt"] == ("office", "email")

    def test_bundle_states_serialise(self, client, entitlements):
        data = client.licences.bundles()[0].to_dict()
        assert set(data) == {"bundle_id", "state", "licence_id", "valid_until", "licensed_addons"}
