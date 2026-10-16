"""Contract tests: the committed signed fixtures in `policy/fixtures/v1/`.

The same fixtures and manifest are read by the admin tool's signing tests, so the client and the
signer are held to one definition of a good and a bad policy. Every failure mode must leave the
client with the last good policy.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vethuq._policy import (
    _FetchFailure,
    _FetchResponse,
    _PolicyClient,
    _PolicyFetcher,
    _PolicyKey,
    _PolicyKeys,
    _PolicyStore,
)
from vethuq.enums import PolicySource, PolicyStatus

FIXTURES = Path(__file__).resolve().parents[4] / "policy" / "fixtures" / "v1"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
LAST_GOOD_SEQUENCE = 5


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _key(kid: str, standby: bool = False) -> _PolicyKey:
    text = (FIXTURES / "keys" / f"{kid}.pub").read_text(encoding="utf-8")
    return _PolicyKey.from_b64url(kid, text, standby)


def _keys() -> _PolicyKeys:
    """The current policy key and the standby key, as a client has them embedded."""
    return _PolicyKeys([_key(MANIFEST["kid"]), _key(MANIFEST["standby_kid"], standby=True)])


class _Clock:
    now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class _Fetcher:
    def __init__(self) -> None:
        self.answers: list = []

    def serve(self, *answers) -> None:
        self.answers = list(answers)

    def attempts(self, etag_url=None, etag=None):
        yield from self.answers


def _ok(raw: bytes, etag: str | None = None) -> _FetchResponse:
    return _FetchResponse("https://policy.test/p", raw, etag)


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def fetcher() -> _Fetcher:
    return _Fetcher()


@pytest.fixture
def client(tmp_path, fetcher, clock) -> _PolicyClient:
    return _PolicyClient(tmp_path / "policy", keys=_keys(), fetcher=fetcher, clock=clock)


@pytest.fixture
def with_last_good(client, fetcher, clock) -> _PolicyClient:
    """A client that has accepted the `valid` fixture, with a refresh due again."""
    fetcher.serve(_ok(_fixture("valid.envelope.json"), etag='"good"'))
    first = client.refresh(force=True)
    assert (first.status, first.policy.sequence) == (PolicyStatus.UPDATED, LAST_GOOD_SEQUENCE)
    clock.now += 2 * 24 * 3600
    return client


def _kept(result, client) -> None:
    """The result and a fresh read both show the last good policy."""
    assert result.policy.sequence == LAST_GOOD_SEQUENCE and result.source is PolicySource.CACHE
    again = client.current()
    assert (again.policy.sequence, again.source) == (LAST_GOOD_SEQUENCE, PolicySource.CACHE)


def _entries(expect: str):
    return [e for e in MANIFEST["fixtures"] if e["expect"] == expect]


def test_the_manifest_names_files_that_exist():
    for entry in MANIFEST["fixtures"]:
        assert (FIXTURES / entry["file"]).is_file(), entry["file"]


def test_the_fixtures_are_up_to_date(monkeypatch):
    import importlib.util  # noqa: PLC0415

    path = FIXTURES.parents[2] / "tools" / "policy" / "make_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name, text in module.build().items():
        assert (FIXTURES / name).read_text(encoding="utf-8") == text, name


class TestAcceptedFixtures:
    @pytest.mark.parametrize("entry", _entries("accepted"), ids=lambda e: e["file"])
    def test_a_good_policy_is_accepted_on_a_fresh_client(self, client, fetcher, entry):
        fetcher.serve(_ok(_fixture(entry["file"])))

        result = client.refresh(force=True)

        assert result.status is PolicyStatus.UPDATED
        assert result.policy.sequence == entry["sequence"]

    def test_unknown_extra_fields_are_ignored_but_kept(self, client, fetcher):
        fetcher.serve(_ok(_fixture("unknown-fields.envelope.json")))

        policy = client.refresh(force=True).policy

        assert policy.raw["future_section"] == {"x": 1}
        assert [n.id for n in policy.notices] == ["active"]


class TestRejectedFixturesKeepTheLastGoodPolicy:
    @pytest.mark.parametrize("entry", _entries("rejected"), ids=lambda e: e["file"])
    def test_a_bad_policy_is_refused(self, with_last_good, fetcher, entry):
        fetcher.serve(_ok(_fixture(entry["file"])))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.REJECTED
        _kept(result, with_last_good)

    def test_a_higher_schema_major_asks_for_an_update_and_keeps_the_policy(
        self, with_last_good, fetcher
    ):
        (entry,) = _entries("update_required")
        fetcher.serve(_ok(_fixture(entry["file"])))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.UPDATE_REQUIRED and result.update_required
        _kept(result, with_last_good)

    def test_a_newer_good_policy_still_replaces_it_afterwards(self, with_last_good, fetcher):
        fetcher.serve(_ok(_fixture("lower-sequence.envelope.json")))
        with_last_good.refresh(force=True)
        fetcher.serve(_ok(_fixture("valid-newer.envelope.json")))

        assert with_last_good.refresh(force=True).policy.sequence == 6


class TestFailuresThatAreNotFiles:
    def test_an_oversize_payload_is_refused(self, with_last_good, tmp_path):
        import http.server  # noqa: PLC0415
        import threading  # noqa: PLC0415

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b"x" * (_PolicyFetcher.MAX_BYTES + 1)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/p"
            with_last_good._fetcher = _PolicyFetcher([url], schemes=("http",))

            result = with_last_good.refresh(force=True)
        finally:
            server.shutdown()
            server.server_close()

        assert result.status is PolicyStatus.OFFLINE and "too large" in result.detail
        _kept(result, with_last_good)

    def test_every_url_failing_is_offline(self, with_last_good, fetcher):
        fetcher.serve(
            _FetchFailure("https://a", "timed out"), _FetchFailure("https://b", "HTTP 500")
        )

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.OFFLINE
        _kept(result, with_last_good)

    def test_an_unchanged_etag_keeps_the_policy(self, with_last_good, fetcher):
        fetcher.serve(_FetchResponse("https://policy.test/p", None, '"good"', not_modified=True))

        result = with_last_good.refresh(force=True)

        assert result.status is PolicyStatus.UNCHANGED
        _kept(result, with_last_good)


class TestNoticeWindows:
    def test_only_the_active_notice_is_shown(self, client, fetcher):
        windows = MANIFEST["notice_windows"]
        fetcher.serve(_ok(_fixture(windows["file"])))
        policy = client.refresh(force=True).policy
        now = datetime(2026, 10, 15, tzinfo=UTC)

        active = [n.id for n in policy.active_notices(now)]
        everything = [n.id for n in policy.notices]

        assert active == windows["active"]
        assert set(windows["expired"] + windows["future"]) <= set(everything) - set(active)

    def test_a_notice_ends_when_its_window_does(self, client, fetcher):
        fetcher.serve(_ok(_fixture("valid.envelope.json")))
        policy = client.refresh(force=True).policy

        assert "expired" in [
            n.id for n in policy.active_notices(datetime(2020, 1, 1, 12, tzinfo=UTC))
        ]
        assert "expired" not in [
            n.id for n in policy.active_notices(datetime(2026, 1, 1, tzinfo=UTC))
        ]
        assert "future" in [n.id for n in policy.active_notices(datetime(2100, 1, 1, tzinfo=UTC))]


REVOCATION = MANIFEST["revocation"]
ACTIVE = MANIFEST["kid"]
STANDBY = MANIFEST["standby_kid"]


def _revoke(client, fetcher, clock, name: str):
    clock.now += 2 * 24 * 3600
    fetcher.serve(_ok(_fixture(name)))
    return client.refresh(force=True)


class TestKeyRevocation:
    def test_a_standby_policy_revokes_a_key_and_is_accepted(self, with_last_good, fetcher, clock):
        spec = REVOCATION["revoked_by_standby"]

        result = _revoke(with_last_good, fetcher, clock, spec["file"])

        assert result.status is PolicyStatus.UPDATED and result.policy.sequence == spec["sequence"]
        assert with_last_good.revoked_key_ids() == frozenset(spec["revokes"])
        assert result.revoked_key_ids == frozenset(spec["revokes"])

    def test_everything_the_revoked_key_signs_is_refused_afterwards(
        self, with_last_good, fetcher, clock
    ):
        _revoke(with_last_good, fetcher, clock, REVOCATION["revoked_by_standby"]["file"])

        for name in REVOCATION["refused_once_revoked"]:
            result = _revoke(with_last_good, fetcher, clock, name)
            assert result.status is PolicyStatus.REJECTED, name
            assert result.policy.sequence == REVOCATION["revoked_by_standby"]["sequence"], name

    def test_the_revocation_survives_a_restart(self, tmp_path, fetcher, clock, with_last_good):
        _revoke(with_last_good, fetcher, clock, REVOCATION["revoked_by_standby"]["file"])
        restarted = _PolicyClient(tmp_path / "policy", keys=_keys(), fetcher=fetcher, clock=clock)

        assert restarted.revoked_key_ids() == frozenset({ACTIVE})
        fetcher.serve(_ok(_fixture("signed-by-revoked-key.envelope.json")))
        clock.now += 2 * 24 * 3600
        result = restarted.refresh(force=True)

        assert result.status is PolicyStatus.REJECTED and "revoked" in result.detail
        assert result.policy.sequence == REVOCATION["revoked_by_standby"]["sequence"]

    def test_a_revocation_signed_by_the_current_key_is_ignored(
        self, with_last_good, fetcher, clock
    ):
        spec = REVOCATION["no_authority"]

        result = _revoke(with_last_good, fetcher, clock, spec["file"])

        assert result.status is PolicyStatus.UPDATED and result.policy.sequence == spec["sequence"]
        assert with_last_good.revoked_key_ids() == frozenset()
        assert spec["ignored"][0] in result.policy.revoked_key_ids  # in the policy, not honoured

    def test_entries_naming_the_signer_or_a_standby_key_are_ignored(
        self, with_last_good, fetcher, clock
    ):
        spec = REVOCATION["ignored_entries"]

        _revoke(with_last_good, fetcher, clock, spec["file"])

        revoked = with_last_good.revoked_key_ids()
        assert revoked == frozenset(spec["revokes"])
        assert not (revoked & {STANDBY, *spec["ignored"]})

    def test_the_standby_key_keeps_working_after_it_revoked(self, with_last_good, fetcher, clock):
        _revoke(with_last_good, fetcher, clock, REVOCATION["revoked_by_standby"]["file"])

        result = _revoke(with_last_good, fetcher, clock, REVOCATION["ignored_entries"]["file"])

        assert result.status is PolicyStatus.UPDATED
        assert result.policy.sequence == REVOCATION["ignored_entries"]["sequence"]

    def test_the_revoked_set_only_grows(self, with_last_good, fetcher, clock):
        _revoke(with_last_good, fetcher, clock, REVOCATION["revoked_by_standby"]["file"])
        _revoke(with_last_good, fetcher, clock, REVOCATION["ignored_entries"]["file"])

        # The second policy does not name the first revoked key, yet it stays revoked.
        assert with_last_good.revoked_key_ids() == frozenset(
            {
                *REVOCATION["revoked_by_standby"]["revokes"],
                *REVOCATION["ignored_entries"]["revokes"],
            }
        )

    def test_when_the_saved_policys_key_is_revoked_trust_fails_closed_and_it_says_so(
        self, tmp_path, with_last_good
    ):
        store = _PolicyStore(tmp_path / "policy")
        store.write_state(store.read_state().with_revoked([ACTIVE]))

        result = with_last_good.current()

        assert result.source is PolicySource.BASELINE
        assert result.trust_message == result.SIGNER_REVOKED_MESSAGE
        assert result.to_dict()["revoked_key_ids"] == [ACTIVE]

    def test_a_damaged_revoked_set_never_blocks_local_work(self, tmp_path, with_last_good):
        (tmp_path / "policy" / "state.json").write_text("{ not json", encoding="utf-8")

        result = with_last_good.current()

        assert with_last_good.revoked_key_ids() == frozenset()
        assert result.policy is not None

    def test_an_unwritable_folder_still_gives_the_revocation_for_the_session(
        self, tmp_path, fetcher, clock
    ):
        # No cache folder can be written: the policy is still returned, and nothing raises.
        blocked = tmp_path / "blocked"
        blocked.write_text("a file where a folder should be")
        client = _PolicyClient(blocked / "policy", keys=_keys(), fetcher=fetcher, clock=clock)
        fetcher.serve(_ok(_fixture(REVOCATION["revoked_by_standby"]["file"])))

        result = client.refresh(force=True)

        assert result.policy.sequence == REVOCATION["revoked_by_standby"]["sequence"]
