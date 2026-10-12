from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import vethuq
from tests import fake_pipeline as fp
from tests.credits_helpers import grace_of
from vethuq import errors
from vethuq._credits import _Clock
from vethuq._indexing import _Indexer
from vethuq._metrics import ALLOWED, _Batch
from vethuq.metrics import Metrics, MetricsBatch, MetricsSendResult, MetricsStatus

SCHEMA = Path(__file__).resolve().parents[3] / "metrics" / "schema" / "v1"


class Time:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)

    def next_day(self, days: int = 1) -> None:
        self.now = (self.now + timedelta(days=days)).replace(hour=1)


class Collector:
    """A stand-in for the collector: keeps what it was sent."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.status = 200
        self.fail: Exception | None = None

    def __call__(self, url: str, body: bytes) -> tuple[int, str]:
        if self.fail:
            raise self.fail
        self.posts.append((url, json.loads(body)))
        return self.status, "{}"


@pytest.fixture
def time(monkeypatch):
    clock = Time()
    monkeypatch.setattr(_Clock, "system", staticmethod(lambda: clock.now))
    return clock


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)


@pytest.fixture
def collector():
    return Collector()


@pytest.fixture
def client(tmp_path, time, collector):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client._credit_engine().policy = lambda: {
            "metrics": {
                "enabled": True,
                "endpoint": "https://metrics.example.test/",
                "max_batch_bytes": 65536,
                "bonus_percent": 10,
            }
        }
        client._metrics_engine().sender = collector
        yield client


def write(folder, name, *pages, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(fp.pdf_document(*pages, **extra), encoding="utf-8")


@pytest.fixture
def worked(client, tmp_path):
    """One day's work, with metrics sharing still off."""
    write(tmp_path / "d", "a.pdf", fp.scanned_page("words on the scan"), fp.native_page())
    write(tmp_path / "d", "bad.pdf", fp.native_page(), error="password")
    source = client.sources.create(tmp_path / "d")
    client.index.run(source.id, workers=0)
    return source


class TestOptIn:
    def test_off_by_default(self, client):
        assert isinstance(client.metrics, Metrics)
        status = client.metrics.status()
        assert isinstance(status, MetricsStatus)
        assert (status.opted_in, status.available, status.bonus_active) == (False, True, False)
        assert not client.settings.metrics.get_opt_in()

    def test_opting_in_and_out(self, client):
        assert client.metrics.opt_in().opted_in
        assert client.settings.metrics.get_opt_in()
        assert not client.metrics.opt_out().opted_in

    def test_the_setting(self, client):
        client.settings.metrics.set_opt_in(True)
        assert client.metrics.status().opted_in
        client.settings.metrics.reset_opt_in()
        assert not client.metrics.status().opted_in
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.metrics.set_opt_in("yes")

    def test_nothing_is_sent_unless_you_opted_in(self, client, collector, worked):
        result = client.metrics.send(force=True)
        assert result.status == "not_opted_in" and not result.sent
        assert collector.posts == []

    def test_a_run_does_not_send_without_opting_in(self, client, collector, worked):
        assert collector.posts == []

    def test_unavailable_when_the_policy_says_so(self, client, collector, worked):
        client.metrics.opt_in()
        for raw in (
            {"metrics": {"enabled": False, "endpoint": "https://x.test"}},
            {"metrics": {"enabled": True, "endpoint": ""}},
            {"metrics": {"enabled": True, "endpoint": "http://x.test"}},
            {},
        ):
            client._credit_engine().policy = lambda raw=raw: raw
            client._credit_engine().terms  # noqa: B018
            with client._db().session() as session:
                from vethuq._settings import _Settings

                _Settings.reset(session, "credits_terms")
            result = client.metrics.send(force=True)
            assert result.status == "disabled", raw
            assert not client.metrics.status().available
        assert collector.posts == []


class TestBatch:
    def test_it_holds_closed_days_only(self, client, time, worked):
        client.metrics.opt_in()
        assert client.metrics.preview().to_dict()["days"] == []  # today is not closed yet
        time.next_day()
        batch = client.metrics.preview()
        assert isinstance(batch, MetricsBatch)
        assert [d["day"] for d in batch.data["days"]] == ["2026-10-12"]

    def test_what_it_holds(self, client, time, worked):
        time.next_day()
        data = client.metrics.preview().to_dict()
        (day,) = data["days"]
        by_source = {(p["page_source"], p["band"]): p for p in day["pages"]}
        ocr = by_source[("ocr", "medium")]
        assert (ocr["pages"], ocr["passes"], ocr["credits_milli"]) == (1, 1, 1000)
        assert ocr["phase"] == "quick" and ocr["language"] == "en" and ocr["size_bucket"] == "m"
        assert ocr["file_type"] == "pdf" and ocr["engine"] == "fake-ocr 1.0"
        native = by_source[("native", "high")]
        assert (native["pages"], native["credits_milli"], native["phase"]) == (1, 0, "")
        assert day["failures"] == [{"file_type": "pdf", "code": "password", "count": 1}]
        assert data["settings"] == {
            "workers": "auto",
            "retry_attempts": 0,
            "languages": ["en"],
            "confidence_bands": [70, 80, 90],
        }
        assert data["client"]["vethuq"] == client.version.vethuq
        assert data["client"]["python"].count(".") == 1

    def test_it_holds_nothing_identifying(self, client, time, worked, tmp_path):
        time.next_day()
        text = client.metrics.preview().to_json()
        for secret in (str(tmp_path), "a.pdf", "bad.pdf", "words on the scan", "d"):
            if secret != "d":
                assert secret not in text
        assert "source" not in text.replace("page_source", "")
        assert "path" not in text

    def test_the_install_id_is_random_and_stable(self, client, time):
        first = client.metrics.preview().data["install_id"]
        assert len(first) == 32 and first == client.metrics.preview().data["install_id"]
        assert (
            first
            != vethuq.VethuQ(db_path=client.db_path.parent / "other.db")
            .metrics.preview()
            .data["install_id"]
        )

    def test_the_fields_are_the_ones_on_the_list(self, client, time, worked):
        time.next_day()
        data = client.metrics.preview().to_dict()
        _Batch.check(data)
        data["days"][0]["pages"][0]["path"] = "/home/me/x.pdf"
        with pytest.raises(ValueError, match="unexpected"):
            _Batch.check(data)

    def test_it_matches_the_published_schema(self, client, time, worked):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads((SCHEMA / "batch.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        time.next_day()
        validator.validate(client.metrics.preview().to_dict())
        validator.validate(
            vethuq.VethuQ(db_path=client.db_path.parent / "e.db").metrics.preview().to_dict()
        )
        props = schema["properties"]
        assert set(props) == ALLOWED["batch"]

    def test_a_big_backlog_is_split_by_size(self, client, time, tmp_path, collector):
        client._credit_engine().policy = lambda: {
            "metrics": {"enabled": True, "endpoint": "https://m.test", "max_batch_bytes": 900}
        }
        write(tmp_path / "d", "a.pdf", fp.scanned_page("one"))
        client.sources.create(tmp_path / "d")
        for n in range(3):
            write(tmp_path / "d", f"{n}.pdf", fp.scanned_page(f"words of file {n}"))
            client.index.run()
            time.next_day()
        client.metrics.opt_in()
        sent_days = []
        for _ in range(5):
            result = client.metrics.send(force=True)
            assert result.sent
            sent_days += [d["day"] for _, b in collector.posts[len(sent_days) :] for d in b["days"]]
            if client.metrics.status().pending_days == 0:
                break
        assert sorted(set(sent_days)) == sent_days  # each day once, oldest first
        assert len(collector.posts) >= 2
        assert all(len(json.dumps(b)) <= 1800 for _, b in collector.posts)


class TestSending:
    def test_a_batch_is_sent_and_remembered(self, client, time, worked, collector):
        client.metrics.opt_in()
        time.next_day()
        result = client.metrics.send()
        assert isinstance(result, MetricsSendResult) and result.sent
        assert (result.days, result.size_bytes > 0) == (1, True)
        ((url, body),) = collector.posts
        assert url == "https://metrics.example.test/v1/batch"
        assert body["schema"] == 1 and [d["day"] for d in body["days"]] == ["2026-10-12"]
        status = client.metrics.status()
        assert (status.sent_through, status.pending_days) == ("2026-10-12", 0)
        assert status.last_sent_at

    def test_days_are_not_sent_twice(self, client, time, worked, collector):
        client.metrics.opt_in()
        time.next_day()
        client.metrics.send(force=True)
        client.metrics.send(force=True)
        assert [len(b["days"]) for _, b in collector.posts] == [1, 0]  # then a heartbeat

    def test_with_nothing_to_send_it_still_checks_in(self, client, collector):
        client.metrics.opt_in()
        assert client.metrics.send().sent
        assert collector.posts[0][1]["days"] == []

    def test_at_most_once_a_day(self, client, time, collector):
        client.metrics.opt_in()
        assert client.metrics.send().sent
        assert client.metrics.send().status == "nothing_to_do"
        assert client.metrics.send(force=True).sent
        time.next_day()
        assert client.metrics.send().sent
        assert len(collector.posts) == 3

    def test_a_run_sends_at_its_end(self, client, time, collector, tmp_path, worked):
        client.metrics.opt_in()
        time.next_day()
        write(tmp_path / "d", "c.pdf", fp.native_page("one more native page, quite long"))
        client.index.run()
        assert len(collector.posts) == 1 and collector.posts[0][1]["days"][0]["day"] == "2026-10-12"

    def test_a_failing_collector_never_breaks_a_run(self, client, time, collector, tmp_path):
        client.metrics.opt_in()
        collector.fail = ConnectionError("offline")
        write(tmp_path / "d", "c.pdf", fp.native_page("one more native page, quite long"))
        client.sources.create(tmp_path / "d")
        run = client.index.run()
        assert run.status.value == "completed"
        result = client.metrics.send(force=True)
        assert result.status == "failed" and "offline" in result.detail
        assert client.metrics.status().last_sent_at is None

    def test_a_refusing_collector_is_a_failure(self, client, time, collector):
        client.metrics.opt_in()
        collector.status = 422
        result = client.metrics.send()
        assert result.status == "failed" and "422" in result.detail
        collector.status = 200
        assert client.metrics.send(force=True).sent

    def test_nothing_but_https(self):
        from vethuq._metrics.service import post

        with pytest.raises(ValueError, match="https"):
            post("http://example.test/v1/batch", b"{}")
        with pytest.raises(ValueError, match="https"):
            post("file:///etc/passwd", b"{}")

    def test_result_dict_and_json(self, client):
        client.metrics.opt_in()
        result = client.metrics.send()
        assert json.loads(result.to_json()) == result.to_dict()
        status = client.metrics.status()
        assert json.loads(status.to_json()) == status.to_dict()


class TestDeleteData:
    def test_the_collector_is_asked_and_the_id_changes(self, client, collector):
        client.metrics.opt_in()
        client.metrics.send()
        before = client.metrics.preview().data["install_id"]
        result = client.metrics.delete_data()
        assert result.status == "sent"
        url, body = collector.posts[-1]
        assert url == "https://metrics.example.test/v1/delete" and body == {"install_id": before}
        assert client.metrics.preview().data["install_id"] != before
        status = client.metrics.status()
        assert (status.sent_through, status.last_sent_at, status.opted_in) == (None, None, True)

    def test_a_refusal_changes_nothing(self, client, collector):
        before = client.metrics.preview().data["install_id"]
        collector.status = 500
        assert client.metrics.delete_data().status == "failed"
        assert client.metrics.preview().data["install_id"] == before

    def test_without_a_collector(self, client):
        client._credit_engine().policy = lambda: {}
        with client._db().session() as session:
            from vethuq._settings import _Settings

            _Settings.reset(session, "credits_terms")
        assert client.metrics.delete_data().status == "disabled"

    def test_a_network_error_is_reported(self, client, collector):
        collector.fail = OSError("down")
        assert "down" in client.metrics.delete_data().detail


class TestBonus:
    def test_it_starts_the_day_after_the_first_send(self, client, time, worked):
        client.metrics.opt_in()
        time.next_day()
        assert client.credits.balance().bonus_active is False  # nothing sent yet
        client.metrics.send()
        assert not client.credits.balance().bonus_active  # it is the same day
        time.next_day()
        balance = client.credits.balance()
        assert balance.bonus_active and balance.bonus == 50
        assert (balance.daily_allowance, balance.daily) == (550, 550)
        assert client.metrics.status().bonus_active

    def test_it_applies_to_the_daily_credits_and_the_grace_only(self, client, time, worked):
        client.metrics.opt_in()
        client.metrics.send()
        time.next_day()
        balance = client.credits.balance()
        assert (balance.one_off, grace_of(client)) == (2000, 11)  # 2% of 550

    def test_it_lapses_after_seven_days_without_a_send(self, client, time):
        client.metrics.opt_in()
        client.metrics.send()
        time.next_day()
        assert client.credits.balance().bonus_active
        time.next_day(6)
        assert client.credits.balance().bonus_active  # 7 days after the send
        time.next_day()
        assert not client.credits.balance().bonus_active
        client.metrics.send()
        time.next_day()
        assert client.credits.balance().bonus_active

    def test_opting_out_ends_it_the_next_day(self, client, time):
        client.metrics.opt_in()
        client.metrics.send()
        time.next_day()
        assert client.credits.balance().bonus_active
        client.metrics.opt_out()
        time.next_day()
        assert not client.credits.balance().bonus_active

    def test_the_bonus_percent_is_capped(self, client, time):
        client._credit_engine().policy = lambda: {
            "metrics": {"enabled": True, "endpoint": "https://m.test", "bonus_percent": 90},
            "caps": {"metrics_bonus_percent": 15},
        }
        client.metrics.opt_in()
        client.metrics.send()
        time.next_day()
        assert client.credits.balance().bonus == 75

    def test_it_never_touches_what_a_page_costs(self, client, time, tmp_path):
        client.metrics.opt_in()
        client.metrics.send()
        time.next_day()
        write(tmp_path / "d", "s.pdf", fp.scanned_page())
        client.sources.create(tmp_path / "d")
        assert client.index.run().credits_charged == 1.0
