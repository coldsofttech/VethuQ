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
)
from vethuq.enums import PolicySource, PolicyStatus

FIXTURES = Path(__file__).resolve().parents[4] / "policy" / "fixtures" / "v1"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
LAST_GOOD_SEQUENCE = 5


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _keys() -> _PolicyKeys:
    text = (FIXTURES / "keys" / f"{MANIFEST['kid']}.pub").read_text(encoding="utf-8")
    return _PolicyKeys([_PolicyKey.from_b64url(MANIFEST["kid"], text)])


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
