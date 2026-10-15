from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.policy_factory import PolicySigner
from vethuq._policy import _FetchResponse, _PolicyClient
from vethuq.enums import PolicyStatus
from vethuq.policy import PolicyClient


class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class _Fetcher:
    def __init__(self, *answers):
        self.answers = list(answers)

    def attempts(self, etag_url=None, etag=None):
        yield from self.answers


ISSUED = datetime(2026, 10, 1, 12, tzinfo=UTC).timestamp()


@pytest.fixture
def signer():
    return PolicySigner()


def _client(tmp_path, signer, clock, *answers):
    return _PolicyClient(
        tmp_path / "p", keys=signer.keys(), fetcher=_Fetcher(*answers), clock=clock
    )


class TestTrustedClock:
    def test_the_offset_comes_from_the_servers_date(self, tmp_path, signer):
        local = ISSUED + 3600
        clock = _Clock(local)
        server = _FetchResponse("https://h/p", signer.signed(1), None, server_time=local + 7200)
        client = _client(tmp_path, signer, clock, server)

        client.refresh(force=True)

        assert client.now().timestamp() == pytest.approx(local + 7200)

    def test_a_304_also_updates_the_offset(self, tmp_path, signer):
        clock = _Clock(ISSUED + 3600)
        raw = signer.signed(1)
        client = _client(
            tmp_path,
            signer,
            clock,
            _FetchResponse("https://h/p", raw, '"e"', server_time=clock.now),
        )
        client.refresh(force=True)
        clock.now += 2 * 86400
        client._fetcher = _Fetcher(
            _FetchResponse(
                "https://h/p", None, '"e"', not_modified=True, server_time=clock.now - 600
            )
        )

        assert client.refresh(force=True).status is PolicyStatus.UNCHANGED
        assert client.now().timestamp() == pytest.approx(clock.now - 600)

    def test_setting_the_clock_back_never_goes_before_the_policy_was_issued(self, tmp_path, signer):
        clock = _Clock(ISSUED + 100)
        client = _client(
            tmp_path, signer, clock, _FetchResponse("https://h/p", signer.signed(1), None)
        )
        client.refresh(force=True)
        clock.now = ISSUED - 10 * 86400  # the user set the date back to revive an old notice

        assert client.now().timestamp() == pytest.approx(ISSUED)

    def test_without_a_policy_or_a_server_date_it_is_the_local_clock(self, tmp_path, signer):
        clock = _Clock(5_000.0)

        assert _client(tmp_path, signer, clock).now().timestamp() == pytest.approx(5_000.0)

    def test_a_server_without_a_date_header_leaves_the_offset_alone(self, tmp_path, signer):
        clock = _Clock(ISSUED + 5)
        client = _client(
            tmp_path, signer, clock, _FetchResponse("https://h/p", signer.signed(1), None)
        )
        client.refresh(force=True)

        assert client.now().timestamp() == pytest.approx(clock.now)


class _Database:
    def __init__(self, path):
        self.db_path = path


class TestPublicApi:
    @pytest.fixture
    def api(self, tmp_path, signer):
        api = PolicyClient(_Database(tmp_path / "data" / "vethuq.db"))
        api._client = _PolicyClient(
            tmp_path / "policy",
            keys=signer.keys(),
            fetcher=_Fetcher(
                _FetchResponse(
                    "https://h/p",
                    signer.signed(
                        1,
                        notices=[
                            {"id": "old", "message": "gone", "ends_at": "2020-01-01T00:00:00Z"},
                            {"id": "now", "message": "here", "severity": "warning"},
                        ],
                        promotions=[{"id": "p1"}],
                        limits=[{"id": "l1"}],
                    ),
                    None,
                )
            ),
        )
        api.refresh(force=True)
        return api

    def test_notices_are_the_active_ones(self, api):
        assert [n.id for n in api.notices()] == ["now"]

    def test_a_section_is_read_only_data(self, api):
        with pytest.raises(TypeError):
            api.section("versions")["new"] = 1  # type: ignore[index]

    def test_a_missing_or_non_object_section_is_empty(self, api):
        assert dict(api.section("nothing")) == {}
        assert dict(api.section("promotions")) == {}  # a list is not an object section
        assert dict(api.section("sequence")) == {}

    def test_an_object_section_is_returned(self, api):
        assert api.section("versions")["pip"]["latest"] == "2.0.0"
