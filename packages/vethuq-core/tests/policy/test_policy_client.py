import json
import subprocess
import sys
import threading

import pytest
from vethuq_core.policy import (
    Baseline,
    PolicyClient,
    PolicyKeys,
    PolicySource,
    PolicyStatus,
)
from vethuq_core.policy.fetch import PolicyFetcher
from vethuq_core.policy.state import PolicyStore


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_client(keys, tmp_path, clock):
    def make(*urls, **kwargs):
        fetcher = PolicyFetcher(urls, schemes=("http", "https"), timeout=0.5)
        return PolicyClient(
            keys=keys, cache_dir=tmp_path / "policy", fetcher=fetcher, clock=clock, **kwargs
        )

    return make


def test_nothing_cached_means_baseline(make_client):
    result = make_client().current()
    assert result.source is PolicySource.BASELINE
    assert result.policy.versions["desktop"].latest == "0.0.0"


def test_fetch_verifies_and_caches(make_client, server, signer, tmp_path):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)), ETag='"1"')
    client = make_client(server.url())
    result = client.refresh()
    assert (result.status, result.source) == (PolicyStatus.UPDATED, PolicySource.FETCHED)
    assert result.policy.sequence == 1
    # A fresh client (a new process) reads it back from disk without any network.
    server.stop()
    again = make_client(server.url()).current()
    assert (again.source, again.policy.sequence) == (PolicySource.CACHE, 1)


def test_all_urls_failing_keeps_the_baseline_and_never_raises(make_client, server):
    result = make_client(server.url("/missing")).refresh()
    assert result.status is PolicyStatus.OFFLINE
    assert result.source is PolicySource.BASELINE
    assert "404" in result.detail


def test_all_urls_failing_keeps_the_last_good_policy(make_client, server, signer, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    client = make_client(server.url())
    client.refresh()
    server.responses.clear()
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    result = client.refresh()
    assert result.status is PolicyStatus.OFFLINE
    assert (result.source, result.policy.sequence) == (PolicySource.CACHE, 1)


def test_falls_through_to_a_mirror_after_a_bad_response(make_client, server, signer):
    server.serve("/primary", signer.envelope(signer.payload(1), sig="A" * 86))
    server.serve("/mirror", signer.envelope(signer.payload(1)))
    result = make_client(server.url("/primary"), server.url("/mirror")).refresh()
    assert result.status is PolicyStatus.UPDATED
    assert [path for path, _ in server.requests] == ["/primary", "/mirror"]


def test_bad_signature_everywhere_is_rejected_not_cached(make_client, server, signer):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1), sig="A" * 86))
    client = make_client(server.url())
    result = client.refresh()
    assert result.status is PolicyStatus.REJECTED
    assert client.current().source is PolicySource.BASELINE


def test_downgrade_is_rejected_and_the_cached_policy_kept(make_client, server, signer, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(5)))
    client = make_client(server.url())
    client.refresh()
    server.serve("/v1/policy.json", signer.envelope(signer.payload(4)))
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    result = client.refresh()
    assert result.status is PolicyStatus.REJECTED
    assert result.policy.sequence == 5


def test_newer_policy_replaces_the_cached_one(make_client, server, signer, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    client = make_client(server.url())
    client.refresh()
    server.serve("/v1/policy.json", signer.envelope(signer.payload(2)))
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    assert client.refresh().policy.sequence == 2
    assert client.current().policy.sequence == 2


def test_refetching_the_same_policy_is_unchanged(make_client, server, signer, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(3)))
    client = make_client(server.url())
    client.refresh()
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    assert client.refresh().status is PolicyStatus.UNCHANGED


def test_etag_gives_a_not_modified(make_client, server, signer, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)), ETag='"x"')
    client = make_client(server.url())
    client.refresh()
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    result = client.refresh()
    assert result.status is PolicyStatus.UNCHANGED
    assert server.requests[-1][1].get("If-None-Match") == '"x"'


def test_checks_at_most_once_a_day_unless_forced(make_client, server, signer, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    client = make_client(server.url())
    client.refresh()
    clock.now += 3600
    assert client.refresh().status is PolicyStatus.SKIPPED
    assert len(server.requests) == 1
    assert client.refresh(force=True).status is PolicyStatus.UNCHANGED
    assert len(server.requests) == 2


def test_a_failed_check_is_retried_after_an_hour_not_a_day(make_client, server, clock):
    client = make_client(server.url("/missing"))
    client.refresh()
    clock.now += 60
    assert client.refresh().status is PolicyStatus.SKIPPED
    clock.now += PolicyClient.RETRY_INTERVAL_SECONDS
    assert client.refresh().status is PolicyStatus.OFFLINE
    assert len(server.requests) == 2


def test_higher_schema_keeps_the_last_policy_and_asks_for_an_update(
    make_client, server, signer, clock
):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    client = make_client(server.url())
    client.refresh()
    server.serve("/v1/policy.json", signer.envelope(signer.payload(2, schema_version=2)))
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    result = client.refresh()
    assert result.status is PolicyStatus.UPDATE_REQUIRED
    assert result.update_required and result.policy.sequence == 1
    current = client.current()
    assert current.update_required and "Update VethuQ" in current.detail
    # A later compatible policy clears the flag.
    server.serve("/v1/policy.json", signer.envelope(signer.payload(3)))
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    assert not client.refresh().update_required


def test_standby_revocation_blocks_the_revoked_key(make_client, server, signer, standby, clock):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(10**9)))
    client = make_client(server.url())
    client.refresh()
    server.serve(
        "/v1/policy.json", standby.envelope(standby.payload(1, revoked_key_ids=["policy-1"]))
    )
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    result = client.refresh()
    assert (result.status, result.policy.kid) == (PolicyStatus.UPDATED, "standby-1")
    # The revoked key can no longer sign anything, whatever its sequence.
    server.serve("/v1/policy.json", signer.envelope(signer.payload(10**9 + 1)))
    clock.now += PolicyClient.CHECK_INTERVAL_SECONDS + 1
    assert client.refresh().status is PolicyStatus.REJECTED


def test_a_damaged_cache_falls_back_to_the_baseline(make_client, server, signer, tmp_path):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    make_client(server.url()).refresh()
    (tmp_path / "policy" / "policy.json").write_text("garbage", encoding="utf-8")
    assert make_client(server.url()).current().source is PolicySource.BASELINE


def test_a_tampered_cache_is_not_trusted(make_client, server, signer, tmp_path):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    make_client(server.url()).refresh()
    path = tmp_path / "policy" / "policy.json"
    envelope = json.loads(path.read_bytes())
    envelope["sig"] = "A" * 86
    path.write_text(json.dumps(envelope), encoding="utf-8")
    assert make_client(server.url()).current().source is PolicySource.BASELINE


def test_an_unwritable_cache_still_returns_the_fetched_policy(
    make_client, server, signer, monkeypatch
):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))

    def boom(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(PolicyStore, "write_envelope", boom)
    result = make_client(server.url()).refresh()
    assert result.status is PolicyStatus.UPDATED and "not cached" in result.detail


def test_unexpected_errors_never_escape(make_client, server, monkeypatch):
    client = make_client(server.url())

    def boom(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(client._fetcher, "attempts", boom)
    assert client.refresh().source is PolicySource.BASELINE


def test_background_refresh_runs_on_a_daemon_thread(make_client, server, signer):
    server.serve("/v1/policy.json", signer.envelope(signer.payload(1)))
    client = make_client(server.url())
    thread = client.refresh_in_background()
    assert isinstance(thread, threading.Thread) and thread.daemon
    thread.join(5)
    assert client.current().policy.sequence == 1


def test_default_client_with_no_embedded_keys_uses_the_baseline(tmp_path):
    client = PolicyClient(cache_dir=tmp_path)
    assert client.current().policy == Baseline.policy()
    assert PolicyKeys.embedded().kids == ()


def test_importing_the_package_makes_no_network_call():
    code = (
        "import socket\n"
        "def blocked(*a, **k): raise AssertionError('network used on import')\n"
        "socket.socket.connect = blocked\n"
        "socket.getaddrinfo = blocked\n"
        "import vethuq_core.policy\n"
        "from vethuq_core.policy import PolicyClient\n"
        "print('ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "ok", done.stderr
