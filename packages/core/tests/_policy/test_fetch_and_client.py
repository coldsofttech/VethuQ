from __future__ import annotations

import http.server
import json
import threading

import pytest

from tests.policy_factory import PolicySigner
from vethuq._policy import (
    _FetchFailure,
    _FetchResponse,
    _PolicyClient,
    _PolicyFetcher,
    _PolicyKeys,
    _PolicyState,
    _PolicyStore,
)
from vethuq.enums import PolicySource, PolicyStatus


class _Server:
    """A throwaway local HTTP server whose answers each test sets."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, dict(self.headers)))
                status, headers, body = outer.routes.get(self.path, (404, {}, b""))
                if headers.get("ETag") and self.headers.get("If-None-Match") == headers["ETag"]:
                    status, body = 304, b""
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._server.server_port}{path}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def server():
    server = _Server()
    yield server
    server.close()


def _fetcher(*urls, **kwargs):
    return _PolicyFetcher(urls, schemes=("http",), **kwargs)


class TestPolicyFetcher:
    def test_returns_the_body_and_etag(self, server):
        server.routes["/p"] = (200, {"ETag": '"v1"'}, b"hello")

        (response,) = list(_fetcher(server.url("/p")).attempts())

        assert response == _FetchResponse(server.url("/p"), b"hello", '"v1"')

    def test_identifies_itself_as_the_policy_client_and_not_the_app_version(self, server):
        server.routes["/p"] = (200, {}, b"x")

        list(_fetcher(server.url("/p")).attempts())

        headers = server.requests[0][1]
        assert headers["User-Agent"] == "VethuQ-policy/1"
        assert headers["Accept"] == "application/json"

    def test_sends_the_etag_only_to_the_url_it_came_from(self, server):
        server.routes["/a"] = (200, {}, b"a")
        server.routes["/b"] = (200, {}, b"b")
        fetcher = _fetcher(server.url("/a"), server.url("/b"))

        list(fetcher.attempts(server.url("/b"), '"e"'))

        sent = {path: headers.get("If-None-Match") for path, headers in server.requests}
        assert sent == {"/a": None, "/b": '"e"'}

    def test_a_matching_etag_is_not_modified(self, server):
        server.routes["/p"] = (200, {"ETag": '"v1"'}, b"hello")

        (response,) = list(_fetcher(server.url("/p")).attempts(server.url("/p"), '"v1"'))

        assert response.not_modified is True and response.body is None

    def test_http_errors_are_failures_not_exceptions(self, server):
        failures = list(_fetcher(server.url("/missing")).attempts())

        assert failures == [_FetchFailure(server.url("/missing"), "HTTP 404")]

    def test_tries_each_url_lazily_in_order(self, server):
        server.routes["/b"] = (200, {}, b"b")

        attempts = _fetcher(server.url("/a"), server.url("/b")).attempts()
        first = next(attempts)

        assert isinstance(first, _FetchFailure) and len(server.requests) == 1
        assert next(attempts).body == b"b"

    def test_a_body_over_the_cap_is_refused(self, server):
        server.routes["/big"] = (200, {}, b"x" * 100)

        (failure,) = list(_fetcher(server.url("/big"), max_bytes=50).attempts())

        assert isinstance(failure, _FetchFailure) and "too large" in failure.reason

    def test_a_refused_connection_is_a_failure(self):
        (failure,) = list(_fetcher("http://127.0.0.1:1/p", timeout=0.5).attempts())

        assert isinstance(failure, _FetchFailure)

    def test_only_https_is_allowed_by_default(self):
        (failure,) = list(_PolicyFetcher(["http://example.com/p"]).attempts())

        assert "scheme not allowed" in failure.reason

    def test_other_schemes_are_never_fetched(self):
        (failure,) = list(_PolicyFetcher(["file:///etc/passwd"]).attempts())

        assert "scheme not allowed" in failure.reason


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FakeFetcher:
    """Serves queued answers instead of using the network."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls: list[tuple] = []

    def attempts(self, etag_url=None, etag=None):
        self.calls.append((etag_url, etag))
        yield from self.answers


@pytest.fixture
def signer():
    return PolicySigner()


def _client(tmp_path, signer, fetcher, clock=None, extra=()):
    return _PolicyClient(
        tmp_path / "policy",
        keys=signer.keys(*extra),
        fetcher=fetcher,
        clock=clock or _Clock(),
    )


def _ok(raw, url="https://h/p", etag=None):
    return _FetchResponse(url, raw, etag)


class TestPolicyClient:
    def test_with_nothing_fetched_the_baseline_is_used(self, tmp_path, signer):
        result = _client(tmp_path, signer, _FakeFetcher()).current()

        assert (result.source, result.status) == (PolicySource.BASELINE, PolicyStatus.CURRENT)
        assert result.policy.sequence == 0 and result.update_required is False

    def test_current_makes_no_request(self, tmp_path, signer):
        fetcher = _FakeFetcher()

        _client(tmp_path, signer, fetcher).current()

        assert fetcher.calls == []

    def test_without_keys_there_is_no_request(self, tmp_path):
        fetcher = _FakeFetcher()
        client = _PolicyClient(tmp_path / "policy", keys=_PolicyKeys([]), fetcher=fetcher)

        result = client.refresh(force=True)

        assert result.status is PolicyStatus.SKIPPED and "no policy keys" in result.detail
        assert fetcher.calls == []

    def test_accepts_a_signed_policy_and_caches_it(self, tmp_path, signer):
        raw = signer.signed(3)
        client = _client(tmp_path, signer, _FakeFetcher(_ok(raw, etag='"e"')))

        result = client.refresh()

        assert (result.source, result.status) == (PolicySource.FETCHED, PolicyStatus.UPDATED)
        assert result.policy.sequence == 3 and result.policy.versions["pip"].latest == "2.0.0"
        assert (tmp_path / "policy" / "policy.json").read_bytes() == raw
        again = _client(tmp_path, signer, _FakeFetcher()).current()
        assert (again.source, again.policy.sequence) == (PolicySource.CACHE, 3)

    def test_remembers_the_etag_and_sends_it_next_time(self, tmp_path, signer):
        clock = _Clock()
        first = _FakeFetcher(_ok(signer.signed(1), url="https://h/p", etag='"e1"'))
        _client(tmp_path, signer, first, clock).refresh()
        clock.now += 2 * 24 * 3600
        second = _FakeFetcher(_FetchResponse("https://h/p", None, '"e1"', not_modified=True))

        result = _client(tmp_path, signer, second, clock).refresh()

        assert second.calls == [("https://h/p", '"e1"')]
        assert result.status is PolicyStatus.UNCHANGED and result.policy.sequence == 1

    def test_the_same_policy_again_is_unchanged(self, tmp_path, signer):
        raw = signer.signed(1)
        clock = _Clock()
        _client(tmp_path, signer, _FakeFetcher(_ok(raw)), clock).refresh()
        clock.now += 2 * 24 * 3600

        result = _client(tmp_path, signer, _FakeFetcher(_ok(raw)), clock).refresh()

        assert result.status is PolicyStatus.UNCHANGED

    def test_checks_at_most_once_a_day_unless_forced(self, tmp_path, signer):
        clock = _Clock()
        fetcher = _FakeFetcher(_ok(signer.signed(1)))
        client = _client(tmp_path, signer, fetcher, clock)
        client.refresh()
        clock.now += 3600

        assert client.refresh().status is PolicyStatus.SKIPPED
        assert len(fetcher.calls) == 1
        assert client.refresh(force=True).status is not PolicyStatus.SKIPPED
        assert len(fetcher.calls) == 2
        clock.now += 25 * 3600
        client.refresh()
        assert len(fetcher.calls) == 3

    def test_when_every_url_fails_it_is_offline_and_the_last_policy_stays(self, tmp_path, signer):
        clock = _Clock()
        _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(2))), clock).refresh()
        clock.now += 2 * 24 * 3600

        offline = _client(
            tmp_path,
            signer,
            _FakeFetcher(
                _FetchFailure("https://a", "timed out"), _FetchFailure("https://b", "HTTP 500")
            ),
            clock,
        ).refresh()

        assert offline.status is PolicyStatus.OFFLINE
        assert "https://a: timed out" in offline.detail and "https://b: HTTP 500" in offline.detail
        assert (offline.source, offline.policy.sequence) == (PolicySource.CACHE, 2)

    def test_after_a_failure_it_waits_an_hour_before_trying_again(self, tmp_path, signer):
        clock = _Clock()
        fetcher = _FakeFetcher(_FetchFailure("https://a", "down"))
        client = _client(tmp_path, signer, fetcher, clock)
        client.refresh()
        clock.now += 1800
        assert client.refresh().status is PolicyStatus.SKIPPED
        clock.now += 2400

        assert client.refresh().status is PolicyStatus.OFFLINE
        assert len(fetcher.calls) == 2

    def test_a_policy_that_cannot_be_trusted_is_rejected(self, tmp_path, signer):
        impostor = PolicySigner("test-1")  # same key id, a different key

        result = _client(tmp_path, signer, _FakeFetcher(_ok(impostor.signed(1)))).refresh()

        assert result.status is PolicyStatus.REJECTED and "signature" in result.detail
        assert result.source is PolicySource.BASELINE
        assert not (tmp_path / "policy" / "policy.json").exists()

    def test_a_rejected_url_falls_through_to_the_next(self, tmp_path, signer):
        impostor = PolicySigner("test-1")
        fetcher = _FakeFetcher(
            _ok(impostor.signed(1), "https://a"), _ok(signer.signed(1), "https://b")
        )

        result = _client(tmp_path, signer, fetcher).refresh()

        assert result.status is PolicyStatus.UPDATED

    def test_a_lower_sequence_is_a_rollback_and_is_refused(self, tmp_path, signer):
        clock = _Clock()
        _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(5))), clock).refresh()
        clock.now += 2 * 24 * 3600

        result = _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(4))), clock).refresh()

        assert result.status is PolicyStatus.REJECTED and "not above" in result.detail
        assert result.policy.sequence == 5

    def test_a_policy_for_a_newer_schema_asks_for_an_update_and_keeps_the_old_policy(
        self, tmp_path, signer
    ):
        clock = _Clock()
        _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(1))), clock).refresh()
        clock.now += 2 * 24 * 3600

        newer = _FakeFetcher(_ok(signer.signed(2, schema_version=2)))

        result = _client(tmp_path, signer, newer, clock).refresh()

        assert result.status is PolicyStatus.UPDATE_REQUIRED and result.update_required is True
        assert result.policy.sequence == 1
        current = _client(tmp_path, signer, _FakeFetcher()).current()
        assert current.update_required is True
        assert current.detail == "Update VethuQ to receive new policy."

    def test_a_later_compatible_policy_clears_the_update_request(self, tmp_path, signer):
        clock = _Clock()
        too_new = _FakeFetcher(_ok(signer.signed(1, schema_version=2)))
        _client(tmp_path, signer, too_new, clock).refresh()
        clock.now += 2 * 24 * 3600

        result = _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(2))), clock).refresh()

        assert result.status is PolicyStatus.UPDATED and result.update_required is False
        assert _client(tmp_path, signer, _FakeFetcher()).current().update_required is False

    def test_a_standby_policy_revokes_a_key_and_it_is_refused_from_then_on(self, tmp_path, signer):
        standby = PolicySigner("standby-1", standby=True)
        clock = _Clock()
        revoking = _FakeFetcher(_ok(standby.signed(1, revoked_key_ids=["test-1"])))
        _client(tmp_path, signer, revoking, clock, (standby,)).refresh()
        clock.now += 2 * 24 * 3600

        later = _FakeFetcher(_ok(signer.signed(9)))

        result = _client(tmp_path, signer, later, clock, (standby,)).refresh()

        assert result.status is PolicyStatus.REJECTED and "revoked" in result.detail

    def test_a_tampered_cache_is_ignored(self, tmp_path, signer):
        _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(1)))).refresh()
        (tmp_path / "policy" / "policy.json").write_bytes(b"{broken")

        result = _client(tmp_path, signer, _FakeFetcher()).current()

        assert result.source is PolicySource.BASELINE

    def test_a_cached_policy_signed_by_a_key_that_was_dropped_is_ignored(self, tmp_path, signer):
        _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(1)))).refresh()
        other = PolicySigner("other")

        result = _client(tmp_path, other, _FakeFetcher()).current()

        assert result.source is PolicySource.BASELINE

    def test_a_folder_that_cannot_be_written_still_gives_the_policy_for_the_session(
        self, tmp_path, signer
    ):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        client = _PolicyClient(
            blocker / "policy", keys=signer.keys(), fetcher=_FakeFetcher(_ok(signer.signed(1)))
        )

        result = client.refresh()

        assert result.status is PolicyStatus.UPDATED and result.policy.sequence == 1
        assert "not cached" in result.detail

    def test_refresh_never_raises(self, tmp_path, signer):
        class Exploding:
            def attempts(self, *args):
                raise RuntimeError("boom")

        result = _client(tmp_path, signer, Exploding()).refresh()

        assert result.status is PolicyStatus.OFFLINE and result.detail == "unexpected error"

    def test_refresh_in_background_runs_on_a_daemon_thread(self, tmp_path, signer):
        client = _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(1))))

        thread = client.refresh_in_background()
        thread.join(timeout=5)

        assert thread.daemon is True and thread.name == "vethuq-policy"
        assert client.current().policy.sequence == 1

    def test_the_state_file_records_what_was_accepted(self, tmp_path, signer):
        _client(tmp_path, signer, _FakeFetcher(_ok(signer.signed(4)))).refresh()

        state = _PolicyStore(tmp_path / "policy").read_state()

        assert dict(state.accepted) == {"test-1": 4} and state.last_check > 0
        assert json.loads((tmp_path / "policy" / "state.json").read_text())["version"] == 1

    def test_a_real_fetch_over_http_end_to_end(self, tmp_path, signer, server):
        server.routes["/v1/policy.json"] = (200, {"ETag": '"x"'}, signer.signed(2))
        client = _PolicyClient(
            tmp_path / "policy",
            keys=signer.keys(),
            fetcher=_fetcher(server.url("/v1/policy.json")),
        )

        result = client.refresh()

        assert result.status is PolicyStatus.UPDATED and result.policy.sequence == 2
        assert client.current().source is PolicySource.CACHE

