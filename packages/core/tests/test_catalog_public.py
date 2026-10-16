"""`VethuQ().catalog` and `VethuQ().addons.catalog()`: the signed catalog merged with what is
installed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vethuq import VethuQ
from vethuq._catalog import client as catalog_client
from vethuq._policy import _FetchResponse, _PolicyKey, _PolicyKeys
from vethuq.addons import AddonInfo
from vethuq.catalog import AddonState, BundleEntry
from vethuq.enums import AddonStatus, PolicyStatus

FIXTURES = Path(__file__).resolve().parents[3] / "policy" / "fixtures" / "v1"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def trusted(monkeypatch):
    """The fixtures' test keys are the keys this build trusts."""
    kid = MANIFEST["kid"]
    key = _PolicyKey.from_b64url(kid, (FIXTURES / "keys" / f"{kid}.pub").read_text())
    monkeypatch.setattr(_PolicyKeys, "EMBEDDED", (key,))


@pytest.fixture
def served(monkeypatch, trusted):
    """Whatever the test puts in `served["body"]` is what every catalog URL answers."""
    box: dict = {"body": None, "calls": 0}

    def attempts(self, etag_url=None, etag=None):
        box["calls"] += 1
        yield _FetchResponse("https://catalog.test/c", box["body"], None)

    monkeypatch.setattr(catalog_client._PolicyFetcher, "attempts", attempts)
    return box


@pytest.fixture
def client(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


def installed(client, monkeypatch, *infos: AddonInfo) -> None:
    monkeypatch.setattr(client.addons, "list", lambda: list(infos))


def info(addon_id, status=AddonStatus.LOADED, disabled=False, version="1.0.0") -> AddonInfo:
    return AddonInfo(addon_id, f"vethuq-addon-{addon_id}", version, status, "", disabled)


def load(client, served, name="catalog-valid.envelope.json") -> None:
    served["body"] = _fixture(name)
    assert client.catalog.refresh(force=True).status is PolicyStatus.UPDATED


class TestNothingHappensUntilAsked:
    def test_creating_a_client_and_using_it_fetches_nothing(self, client, served):
        client.catalog.current()
        client.catalog.addons()

        assert served["calls"] == 0

    def test_before_a_catalog_only_what_is_installed_is_listed(self, client, monkeypatch):
        installed(client, monkeypatch, info("pdf"), info("csv"))

        entries = client.catalog.addons()

        assert [e.id for e in entries] == ["pdf", "csv"] and not any(e.listed for e in entries)
        assert client.catalog.bundles() == []

    def test_the_cache_folder_is_beside_the_policys(self, client):
        assert client.catalog.directory == Path(client.policy.directory)


class TestRefresh:
    def test_a_signed_catalog_is_fetched_and_cached(self, client, served):
        load(client, served)

        again = VethuQ(client.db_path)
        try:
            assert again.catalog.current().catalog.sequence == 5
        finally:
            again.close()

    def test_nothing_is_fetched_when_the_update_check_is_off(self, client, served):
        client.settings.updates.set_check("off")
        served["body"] = _fixture("catalog-valid.envelope.json")

        result = client.catalog.refresh(force=True)

        assert result.status is PolicyStatus.SKIPPED and served["calls"] == 0

    def test_nothing_is_fetched_when_the_environment_says_off(self, client, served, monkeypatch):
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", "off")

        assert client.catalog.refresh(force=True).status is PolicyStatus.SKIPPED
        assert served["calls"] == 0

    def test_a_catalog_signed_by_a_key_the_policy_revoked_is_refused(self, client, served):
        from vethuq._policy import _PolicyState, _PolicyStore

        store = _PolicyStore(client.policy.directory)
        store.write_state(_PolicyState().with_revoked([MANIFEST["kid"]]))
        served["body"] = _fixture("catalog-valid.envelope.json")

        assert client.catalog.refresh(force=True).status is PolicyStatus.REJECTED

    def test_it_can_run_in_the_background(self, client, served):
        served["body"] = _fixture("catalog-valid.envelope.json")

        client.catalog.refresh_in_background(force=True).join(5)

        assert client.catalog.current().catalog.sequence == 5


class TestMergedWithWhatIsInstalled:
    def test_each_add_on_says_where_it_stands(self, client, served, monkeypatch):
        installed(client, monkeypatch, info("pdf", version="2.1.0"))
        load(client, served)

        entries = {e.id: e for e in client.catalog.addons()}

        assert entries["pdf"].state is AddonState.ENABLED and entries["pdf"].installed
        assert entries["pdf"].installed_version == "2.1.0" and entries["pdf"].licence == "free"
        assert entries["docx"].state is AddonState.NOT_INSTALLED and not entries["docx"].installed
        assert entries["docx"].licence == "licensed" and entries["docx"].bundles == ("office",)
        assert entries["semantic"].status == "coming_soon"

    @pytest.mark.parametrize(
        ("status", "disabled", "state"),
        [
            (AddonStatus.LOADED, False, AddonState.ENABLED),
            (AddonStatus.LOADED, True, AddonState.DISABLED),
            (AddonStatus.DISABLED, True, AddonState.DISABLED),
            (AddonStatus.INCOMPATIBLE, False, AddonState.INCOMPATIBLE),
            (AddonStatus.FAILED, False, AddonState.FAILED),
        ],
    )
    def test_the_states_of_an_installed_add_on(
        self, client, served, monkeypatch, status, disabled, state
    ):
        installed(client, monkeypatch, info("docx", status, disabled))
        load(client, served)

        assert client.catalog.get("docx").state is state

    def test_an_installed_add_on_the_catalog_does_not_list_is_still_shown(
        self, client, served, monkeypatch
    ):
        installed(client, monkeypatch, info("mystery"))
        load(client, served)

        entries = client.catalog.addons()

        assert [e.id for e in entries][-1] == "mystery"
        assert entries[-1].listed is False and entries[-1].state is AddonState.ENABLED

    def test_where_to_ask_is_the_entrys_own_address_or_the_catalogs(self, client, served):
        load(client, served)

        entries = {e.id: e for e in client.catalog.addons()}

        assert entries["semantic"].request_url == "https://example.test/semantic"
        assert entries["pdf"].request_url == "https://example.test/request"

    def test_text_comes_in_the_language_asked_for(self, client, served):
        load(client, served)

        assert client.catalog.get("docx", "es").label == "Documentos de Word"
        assert client.catalog.get("docx").label == "Word documents"

    def test_an_add_on_needing_a_newer_vethuq_says_so(self, client, monkeypatch):
        from vethuq import catalog as catalog_module
        from vethuq._catalog import Catalog, CatalogResult
        from vethuq.enums import PolicySource

        payload = json.loads(
            (FIXTURES.parent.parent / "examples/v1/catalog.example.json").read_text()
        )
        payload["addons"][1]["min_client"] = "9.0.0"  # docx
        result = CatalogResult(
            Catalog.from_payload(payload), PolicySource.CACHE, PolicyStatus.CURRENT
        )
        monkeypatch.setattr(client.catalog, "current", lambda: result)
        monkeypatch.setattr(catalog_module._Versions, "installed", staticmethod(lambda: "1.2.0"))
        installed(client, monkeypatch)

        entries = {e.id: e for e in client.catalog.addons()}

        assert entries["docx"].requires_newer_client and entries["docx"].min_client == "9.0.0"
        assert not entries["pdf"].requires_newer_client

    def test_the_entry_has_json(self, client, served, monkeypatch):
        installed(client, monkeypatch)
        load(client, served)

        data = client.catalog.get("pdf").to_dict()

        assert data["state"] == "not_installed" and data["installed"] is False
        assert json.loads(client.catalog.get("pdf").to_json()) == data

    def test_an_unknown_id_is_none(self, client, served):
        load(client, served)

        assert client.catalog.get("nope") is None and client.catalog.get_bundle("nope") is None


class TestBundles:
    def test_a_bundle_says_which_of_its_add_ons_are_installed(self, client, served, monkeypatch):
        load(client, served)

        (bundle,) = client.catalog.bundles()
        assert isinstance(bundle, BundleEntry)
        assert bundle.addons == ("docx",) and bundle.installed == () and not bundle.complete

        installed(client, monkeypatch, info("docx"))
        (bundle,) = client.catalog.bundles()
        assert bundle.installed == ("docx",) and bundle.complete
        assert bundle.to_dict()["complete"] is True
        assert bundle.request_url == "https://example.test/request"


class TestOnTheAddonsObject:
    def test_addons_catalog_and_bundles_are_the_same_lists(self, client, served):
        load(client, served)

        assert [e.id for e in client.addons.catalog()] == [e.id for e in client.catalog.addons()]
        assert [b.id for b in client.addons.bundles("es")] == ["office"]
