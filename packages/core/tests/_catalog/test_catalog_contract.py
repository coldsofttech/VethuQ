"""The catalog against the committed signed fixtures in `policy/fixtures/v1/` (the same ones the
admin tool's tests read): every failure mode must leave the client with the last good catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vethuq._catalog import Catalog, _CatalogClient, _CatalogUrls
from vethuq._policy import _FetchFailure, _FetchResponse, _PolicyKey, _PolicyKeys
from vethuq.enums import PolicySource, PolicyStatus

FIXTURES = Path(__file__).resolve().parents[4] / "policy" / "fixtures" / "v1"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
CATALOG = MANIFEST["catalog"]
ACTIVE, STANDBY = MANIFEST["kid"], MANIFEST["standby_kid"]
GOOD = CATALOG["valid"]


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _keys() -> _PolicyKeys:
    def key(kid, standby=False):
        text = (FIXTURES / "keys" / f"{kid}.pub").read_text(encoding="utf-8")
        return _PolicyKey.from_b64url(kid, text, standby)

    return _PolicyKeys([key(ACTIVE), key(STANDBY, True)])


class _Clock:
    now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class _Fetcher:
    def __init__(self) -> None:
        self.answers: list = []
        self.calls: list = []

    def serve(self, *answers) -> None:
        self.answers = list(answers)

    def attempts(self, etag_url=None, etag=None):
        self.calls.append((etag_url, etag))
        yield from self.answers


def _ok(raw: bytes, etag: str | None = None) -> _FetchResponse:
    return _FetchResponse("https://catalog.test/c", raw, etag)


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def fetcher():
    return _Fetcher()


@pytest.fixture
def revoked():
    return set()


@pytest.fixture
def enabled():
    return [True]


@pytest.fixture
def client(tmp_path, fetcher, clock, revoked, enabled):
    return _CatalogClient(
        tmp_path / "policy",
        keys=_keys(),
        fetcher=fetcher,
        clock=clock,
        revoked=lambda: frozenset(revoked),
        enabled=lambda: enabled[0],
    )


@pytest.fixture
def with_last_good(client, fetcher, clock):
    fetcher.serve(_ok(_fixture(GOOD["file"]), '"good"'))
    first = client.refresh(force=True)
    assert (first.status, first.catalog.sequence) == (PolicyStatus.UPDATED, GOOD["sequence"])
    clock.now += 2 * 24 * 3600
    return client


def _kept(result, client):
    assert result.catalog.sequence == GOOD["sequence"] and result.source is PolicySource.CACHE
    again = client.current()
    assert (again.catalog.sequence, again.source) == (GOOD["sequence"], PolicySource.CACHE)


class TestAccepted:
    def test_a_good_catalog_is_parsed(self, client, fetcher):
        fetcher.serve(_ok(_fixture(GOOD["file"])))

        result = client.refresh(force=True)

        catalog = result.catalog
        assert result.status is PolicyStatus.UPDATED and result.source is PolicySource.FETCHED
        assert (len(catalog.addons), len(catalog.bundles)) == (GOOD["addons"], GOOD["bundles"])
        assert catalog.addon("docx").bundles == ("office",)
        assert catalog.bundle("office").addons == ("docx",)
        assert catalog.request_url == "https://example.test/request"

    def test_a_newer_catalog_replaces_it(self, with_last_good, fetcher):
        fetcher.serve(_ok(_fixture(CATALOG["valid_newer"]["file"])))

        assert with_last_good.refresh(force=True).catalog.sequence == 6

    @pytest.mark.parametrize("entry", CATALOG["accepted"], ids=lambda e: e["file"])
    def test_unknown_fields_are_ignored_but_kept(self, client, fetcher, entry):
        fetcher.serve(_ok(_fixture(entry["file"])))

        catalog = client.refresh(force=True).catalog

        assert catalog.sequence == entry["sequence"] and catalog.raw["future_section"] == {"x": 1}
        assert catalog.addon("pdf") is not None


class TestRefusedKeepsTheLastGoodCatalog:
    @pytest.mark.parametrize("entry", CATALOG["rejected"], ids=lambda e: e["file"])
    def test_a_bad_catalog_is_refused(self, with_last_good, fetcher, entry):
        fetcher.serve(_ok(_fixture(entry["file"])))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.REJECTED
        _kept(result, with_last_good)

    def test_a_higher_schema_major_asks_for_an_update_and_keeps_the_catalog(
        self, with_last_good, fetcher
    ):
        fetcher.serve(_ok(_fixture(CATALOG["update_required"][0]["file"])))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.UPDATE_REQUIRED and result.update_required
        _kept(result, with_last_good)

    def test_a_catalog_signed_by_a_revoked_key_is_refused(self, with_last_good, fetcher, revoked):
        revoked.add(ACTIVE)
        fetcher.serve(_ok(_fixture(CATALOG["refused_once_key_revoked"][0])))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.REJECTED and "revoked" in result.detail

    def test_a_cached_catalog_whose_key_is_revoked_is_not_used(self, with_last_good, revoked):
        revoked.add(ACTIVE)

        result = with_last_good.current()

        assert result.source is PolicySource.BASELINE and result.catalog.sequence == 0

    def test_every_url_failing_is_offline(self, with_last_good, fetcher):
        fetcher.serve(
            _FetchFailure("https://a", "timed out"), _FetchFailure("https://b", "HTTP 500")
        )

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.OFFLINE
        _kept(result, with_last_good)

    def test_an_unchanged_etag_keeps_it(self, with_last_good, fetcher):
        fetcher.serve(_FetchResponse("https://catalog.test/c", None, '"good"', not_modified=True))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.UNCHANGED
        _kept(result, with_last_good)

    def test_the_same_catalog_again_is_unchanged(self, with_last_good, fetcher):
        fetcher.serve(_ok(_fixture(GOOD["file"])))

        assert with_last_good.refresh(force=True).status is PolicyStatus.UNCHANGED

    def test_a_damaged_state_file_never_blocks_anything(self, tmp_path, with_last_good):
        (tmp_path / "policy" / "catalog-state.json").write_text("{ nope", encoding="utf-8")

        assert with_last_good.current().catalog.sequence == GOOD["sequence"]

    def test_a_tampered_cache_is_ignored(self, tmp_path, with_last_good):
        cache = tmp_path / "policy" / "catalog.json"
        cache.write_bytes(cache.read_bytes().replace(b"A", b"B", 1))

        assert with_last_good.current().source is PolicySource.BASELINE


class TestWhenItAsks:
    def test_current_makes_no_request(self, client, fetcher):
        client.current()

        assert fetcher.calls == []

    def test_it_asks_about_once_a_day_unless_forced(self, with_last_good, fetcher, clock):
        clock.now -= 25 * 3600  # 23 hours since the last check
        fetcher.calls.clear()

        assert with_last_good.refresh().status is PolicyStatus.SKIPPED
        assert fetcher.calls == []
        assert with_last_good.refresh(force=True).status is not PolicyStatus.SKIPPED

    def test_it_does_not_ask_when_the_update_check_is_off(self, client, fetcher, enabled):
        enabled[0] = False

        result = client.refresh(force=True)

        assert result.status is PolicyStatus.SKIPPED and "turned off" in result.detail
        assert fetcher.calls == []

    def test_it_does_not_ask_without_embedded_keys(self, tmp_path, fetcher):
        client = _CatalogClient(tmp_path / "p", keys=_PolicyKeys([]), fetcher=fetcher)

        assert client.refresh(force=True).status is PolicyStatus.SKIPPED
        assert fetcher.calls == []

    def test_a_failed_check_waits_an_hour(self, client, fetcher, clock):
        fetcher.serve(_FetchFailure("https://a", "down"))
        client.refresh(force=True)
        fetcher.calls.clear()

        clock.now += 30 * 60
        assert client.refresh().status is PolicyStatus.SKIPPED and fetcher.calls == []

    def test_refresh_never_raises(self, client, fetcher):
        class Boom:
            def attempts(self, *a):
                raise RuntimeError("boom")

        client._fetcher = Boom()

        assert client.refresh(force=True).status is PolicyStatus.OFFLINE

    def test_it_can_run_in_the_background(self, client, fetcher):
        fetcher.serve(_ok(_fixture(GOOD["file"])))

        client.refresh_in_background(force=True).join(5)

        assert client.current().catalog.sequence == GOOD["sequence"]

    def test_an_unwritable_folder_still_gives_the_catalog_for_the_session(
        self, tmp_path, fetcher, clock
    ):
        blocked = tmp_path / "blocked"
        blocked.write_text("a file where a folder should be")
        client = _CatalogClient(blocked / "p", keys=_keys(), fetcher=fetcher, clock=clock)
        fetcher.serve(_ok(_fixture(GOOD["file"])))

        result = client.refresh(force=True)

        assert result.catalog.sequence == GOOD["sequence"] and "not cached" in result.detail


class TestUrls:
    def test_the_catalog_is_beside_the_policy_on_every_mirror(self):
        urls = _CatalogUrls.resolve({})

        assert urls[0] == "https://coldsofttech.github.io/vethuq/policy/v1/catalog.json"
        assert all(u.endswith("/policy/v1/catalog.json") for u in urls) and len(urls) == 3

    def test_the_policy_environment_variable_moves_it_too(self):
        urls = _CatalogUrls.resolve({"VETHUQ_POLICY_URLS": "https://mirror.test/x/policy.json"})

        assert urls == ("https://mirror.test/x/catalog.json",)


class TestModel:
    def payload(self, **over):
        data = json.loads((FIXTURES.parents[1] / "examples/v1/catalog.example.json").read_text())
        data["kid"] = "k"
        data.update(over)
        return data

    def test_translations_pick_the_language_with_a_fallback_to_the_base_language(self):
        catalog = Catalog.from_payload(self.payload())
        docx = catalog.addon("docx")

        assert docx.localized("es").label == "Documentos de Word"
        assert docx.localized("es-MX").label == "Documentos de Word"
        assert docx.localized("es_MX").description == docx.description  # not translated: fallback
        assert docx.localized("fr").label == "Word documents"
        assert docx.localized(None).label == "Word documents"

    def test_an_entry_without_the_required_fields_is_skipped_not_fatal(self):
        data = self.payload()
        data["addons"] += [{"id": "x"}, "junk", {"id": "pdf", "label": "dup", "summary": "dup"}]
        data["bundles"] += [{"id": "empty", "label": "E", "summary": "E", "addons": []}]

        catalog = Catalog.from_payload(data)

        assert [a.id for a in catalog.addons] == ["pdf", "docx", "semantic"]
        assert [b.id for b in catalog.bundles] == ["office"]

    def test_only_https_addresses_are_kept(self):
        data = self.payload(request_url="http://insecure.test")
        data["addons"][0]["docs_url"] = "javascript:alert(1)"
        data["addons"][1]["request_url"] = "https://ok.test/x"

        catalog = Catalog.from_payload(data)

        assert catalog.request_url is None and catalog.addon("pdf").docs_url is None
        assert catalog.addon("docx").request_url == "https://ok.test/x"

    def test_an_unknown_status_and_kind_are_kept_as_they_are(self):
        data = self.payload()
        data["addons"][0].update(status="someday", kind="something-new")

        entry = Catalog.from_payload(data).addon("pdf")

        assert (entry.status, entry.kind) == ("someday", "something-new")

    @pytest.mark.parametrize(
        "bad",
        [
            {"sequence": 0},
            {"sequence": True},
            {"kid": ""},
            {"addons": "x"},
            {"schema_version": "1"},
        ],
    )
    def test_a_malformed_document_is_refused(self, bad):
        from vethuq._policy import _PolicyFormatError

        with pytest.raises(_PolicyFormatError):
            Catalog.from_payload(self.payload(**bad))

    def test_to_dict_is_the_signed_payload(self):
        payload = self.payload(future_section={"x": 1})

        assert Catalog.from_payload(payload).to_dict() == payload
