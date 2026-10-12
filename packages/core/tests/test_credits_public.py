from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import vethuq
from tests import fake_pipeline as fp
from vethuq import errors
from vethuq._credits import _Clock
from vethuq._db import _CreditGrant
from vethuq._indexing import _Indexer
from vethuq.credits import CreditBalance, CreditEntry, Credits
from vethuq.enums import CreditEntryKind, CreditSortBy, FileStatus, IndexRunStatus, SortOrder


class Time:
    """The clock credits reset on."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)

    def next_day(self) -> None:
        self.now = (self.now + timedelta(days=1)).replace(hour=1, minute=0)


@pytest.fixture
def time(monkeypatch):
    clock = Time(datetime(2026, 10, 12, 10, 0, tzinfo=UTC))
    monkeypatch.setattr(_Clock, "system", staticmethod(lambda: clock.now))
    return clock


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)


@pytest.fixture
def client(tmp_path, time):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def policy(client, **raw):
    """Use this as the signed policy's payload."""
    client._credit_engine().policy = lambda: raw


def write(folder, name, *pages, **extra):
    path = folder / name
    path.write_text(fp.pdf_document(*pages, **extra), encoding="utf-8")
    return path


def scan(text="scanned words found by ocr", **size):
    return fp.scanned_page(text, **size)


class TestBalance:
    def test_a_new_wallet(self, client):
        assert isinstance(client.credits, Credits)
        balance = client.credits.balance()
        assert isinstance(balance, CreditBalance)
        assert (balance.daily, balance.one_off, balance.grace) == (500, 2000, 10)
        assert balance.total == 2510
        assert balance.daily_allowance == 500 and not balance.bonus_active
        assert balance.next_reset == "2026-10-13T00:00:00+00:00"
        assert client.credits.next_reset() == balance.next_reset

    def test_asking_twice_grants_once(self, client):
        client.credits.balance()
        client.credits.balance()
        grants = [e for e in client.credits.history() if e.kind is CreditEntryKind.GRANT]
        assert sorted(g.note for g in grants) == ["baseline", "starter"]

    def test_the_daily_amount_resets_with_no_rollover(self, client, time, root):
        write(root, "a.pdf", scan(), scan("another page of words"))
        client.sources.create(root)
        client.index.run()
        assert client.credits.balance().daily == 498
        time.next_day()
        balance = client.credits.balance()
        assert (balance.daily, balance.one_off) == (500, 2000)  # not 998; the starter is once
        assert client.credits.history(kind="expire")[0].amount == 498

    def test_the_policy_sets_the_numbers(self, client):
        policy(client, wallets={"local": {"daily": 20, "starter": 0}}, grace_percent=10)
        balance = client.credits.balance()
        assert (balance.daily, balance.one_off, balance.grace) == (20, 0, 2)

    def test_a_policy_change_applies_from_the_next_day(self, client, time):
        policy(client, wallets={"local": {"daily": 20, "starter": 0}})
        assert client.credits.balance().daily == 20
        policy(client, wallets={"local": {"daily": 99, "starter": 0}})
        assert client.credits.balance().daily == 20  # today keeps what it began with
        time.next_day()
        assert client.credits.balance().daily == 99

    def test_a_policy_not_in_force_yet_waits(self, client, time):
        policy(client, wallets={"local": {"daily": 20}})
        client.credits.balance()
        time.next_day()
        policy(client, wallets={"local": {"daily": 99}}, effective_from="2026-10-20")
        assert client.credits.balance().daily == 20
        time.now = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
        assert client.credits.balance().daily == 99

    def test_the_clock_never_goes_backwards(self, client, time):
        client.credits.balance()
        time.next_day()
        client.credits.balance()
        time.now -= timedelta(days=3)  # the computer's clock was set back
        assert client.credits.next_reset() == "2026-10-14T00:00:00+00:00"

    def test_a_promotion_is_added_for_its_days(self, client, time):
        policy(
            client,
            promotions=[
                {
                    "id": "week",
                    "name": "Week",
                    "start_date": "2026-10-12",
                    "end_date": "2026-10-12",
                    "uplift": {"local": {"percent": 50}},
                }
            ],
        )
        balance = client.credits.balance()
        assert (balance.promotional, balance.daily_allowance) == (250, 750)
        time.next_day()
        assert client.credits.balance().promotional == 0

    def test_the_device_ceiling_limits_the_daily_total(self, client):
        policy(
            client,
            caps={"device_daily_ceiling": 600},
            promotions=[
                {
                    "id": "p",
                    "name": "P",
                    "start_date": "2026-10-12",
                    "end_date": "2026-10-12",
                    "uplift": {"local": {"percent": 100}},
                }
            ],
        )
        assert client.credits.balance().daily_allowance == 600

    def test_borrow_mode_takes_yesterdays_grace_off(self, client, time, root):
        policy(client, wallets={"local": {"daily": 2, "starter": 0}}, grace_mode="borrow",
               grace_percent=50)  # fmt: skip
        write(root, "a.pdf", scan("x one"), scan("x two"), scan("x three"))
        client.sources.create(root)
        client.index.run(workers=0)  # 2 daily + 1 grace
        assert client.credits.balance().grace == 0
        time.next_day()
        assert client.credits.balance().daily == 1  # 2 less the 1 of grace used yesterday

    def test_to_dict_and_json(self, client):
        balance = client.credits.balance()
        assert json.loads(balance.to_json()) == balance.to_dict()


class TestCharging:
    def test_a_scanned_a4_page_costs_one_credit(self, client, root):
        write(root, "a.pdf", scan())
        client.sources.create(root)
        run = client.index.run()
        assert run.credits_charged == 1.0 and run.ocr_pages == 1 and run.pages_processed == 1
        assert client.credits.balance().daily == 499
        (charge,) = client.credits.history(kind=CreditEntryKind.CHARGE)
        assert (charge.amount, charge.phase, charge.language, charge.page_number) == (
            1.0,
            "quick",
            "en",
            1,
        )
        assert charge.size_factor == 1.0 and charge.rate_card_version == 1
        assert charge.run_id == run.id and charge.source_id == 1 and charge.note.endswith("a.pdf")

    def test_native_pages_cost_nothing(self, client, root):
        write(root, "a.pdf", fp.native_page(), fp.native_page("some other native words here"))
        client.sources.create(root)
        run = client.index.run()
        assert (run.credits_charged, run.ocr_pages, run.pages_processed) == (0, 0, 2)
        assert client.credits.history(kind="charge") == []

    def test_size_sets_the_price(self, client, root):
        write(root, "a.pdf", scan(**fp.A3))
        write(root, "b.pdf", scan("small page words", width=297.64, height=419.53))
        client.sources.create(root)
        assert client.index.run().credits_charged == 2.25

    def test_a_mixed_page_costs_the_share_its_images_cover(self, client, root):
        side = 400
        write(root, "a.pdf", fp.mixed_page("Native text with enough words in it.", "one", "two",
                                            region_side=side))  # fmt: skip
        client.sources.create(root)
        assert client.index.run().credits_charged == 0.639

    def test_a_mixed_page_with_small_images_costs_the_minimum(self, client, root):
        write(root, "a.pdf", fp.mixed_page("Native text with enough words in it.", "logo"))
        client.sources.create(root)
        assert client.index.run().credits_charged == 0.25

    def test_a_blank_page_costs_the_minimum(self, client, root):
        write(root, "a.pdf", scan(""))
        client.sources.create(root)
        assert client.index.run().credits_charged == 0.25

    def test_duplicates_and_unchanged_files_are_free(self, client, root):
        write(root, "a.pdf", scan())
        write(root, "b.pdf", scan())
        client.sources.create(root)
        assert client.index.run(workers=0).credits_charged == 1.0
        assert client.index.run().credits_charged == 0.0

    def test_a_changed_file_is_charged_again(self, client, root):
        path = write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        write(root, "a.pdf", scan("different words this time"))
        import os
        import time as _t

        os.utime(path, (_t.time() + 9, _t.time() + 9))
        assert client.index.run().credits_charged == 1.0

    def test_an_additional_language_costs_only_its_passes(self, client, root, tmp_path_factory):
        # a document already read in English, now read for Telugu
        from tests.language_addons import TELUGU, LanguageAddonFactory

        folder = tmp_path_factory.mktemp("te")
        import sys

        sys.path.insert(0, str(folder))
        LanguageAddonFactory.install(folder, "telugu", [TELUGU])
        try:
            client.addons  # noqa: B018 - the add-ons are loaded when first used
            client._manager().reload()
            a, b = root / "a", root / "b"
            a.mkdir()
            b.mkdir()
            write(a, "x.pdf", scan("shared words"), fp.native_page())
            write(b, "x.pdf", scan("shared words"), fp.native_page())
            first = client.sources.create(a, languages=["en"])
            second = client.sources.create(b, languages=["te"])
            assert client.index.run(first.id).credits_charged == 1.0
            assert client.index.run(second.id).credits_charged == 1.0  # language_pass
        finally:
            sys.path.remove(str(folder))
            LanguageAddonFactory.forget("vethuq_addon_telugu")

    def test_a_page_larger_than_a0_is_refused_and_free(self, client, root):
        write(root, "a.pdf", scan(width=4000, height=5000))
        source = client.sources.create(root)
        run = client.index.run()
        (info,) = client.sources.list_files(source.id, detailed=True)
        assert info.index.status is FileStatus.ERROR and "too large" in info.index.error
        assert run.credits_charged == 0 and client.credits.balance().daily == 500
        assert client.stats.failures() == {"page_too_large": 1}

    def test_a_file_that_fails_keeps_the_pages_it_read_and_what_they_cost(self, client, root):
        write(root, "a.pdf", scan("first page words"), scan("second page words"), scan("third"),
              error_before_page=3)  # fmt: skip
        write(root, "b.pdf", scan("one"), scan("two"), scan("three"), error_before_page=3)
        client.sources.create(root)
        run = client.index.run(workers=0)
        assert run.files_failed == 2
        assert run.credits_charged == 4.0 and run.ocr_pages == 4
        assert client.credits.balance().daily == 496
        assert client.credits.history(kind="refund") == []
        assert len(client.stats.low_confidence_pages(limit=None)) == 0  # not indexed: not listed

    def test_a_failure_part_way_is_picked_up_where_it_stopped(self, client, root):
        client.settings.index.set_retry_attempts(1)
        write(root, "a.pdf", scan("one"), scan("two"), scan("three"), fail_page_once=3)
        source = client.sources.create(root)
        run = client.index.run(workers=0)
        assert run.files_failed == 0 and run.credits_charged == 3.0  # pages 1 and 2 paid once
        assert len(fp.STATE.ocr_calls) == 3
        (info,) = client.sources.list_files(source.id, detailed=True)
        assert info.index.pages == 3

    def test_a_failed_file_is_resumed_by_the_next_run(self, client, root):
        write(root, "a.pdf", scan("one"), scan("two"), scan("three"), fail_page_once=3)
        source = client.sources.create(root)
        assert client.index.run(workers=0).files_failed == 1
        assert client.credits.balance().daily == 498
        again = client.index.run(workers=0)
        assert again.files_failed == 0 and again.credits_charged == 1.0  # only page 3
        assert client.credits.balance().daily == 497
        (info,) = client.sources.list_files(source.id, detailed=True)
        assert info.index.pages == 3 and info.index.status is FileStatus.INDEXED

    def test_a_retried_file_is_charged_once(self, client, root):
        client.settings.index.set_retry_attempts(2)
        write(root, "a.pdf", scan(), flaky=1)
        client.sources.create(root)
        run = client.index.run(workers=0)
        assert run.files_failed == 0 and run.credits_charged == 1.0
        assert client.credits.balance().daily == 499


class TestRunningOut:
    def test_the_run_waits_for_credits_and_carries_on_after_the_reset(self, client, root, time):
        policy(client, wallets={"local": {"daily": 2, "starter": 0}})
        a = write(root, "a.pdf", scan("page of the first file"))
        b = write(root, "b.pdf", scan("b one"), scan("b two"))
        source = client.sources.create(root)
        run = client.index.run(workers=0)
        assert run.status is IndexRunStatus.WAITING_CREDITS
        assert "reset" in run.error
        files = {f.name: f.index for f in client.sources.list_files(source.id, detailed=True)}
        assert files["a.pdf"].status is FileStatus.INDEXED  # pages already read stay saved
        assert files["b.pdf"].status is FileStatus.PENDING  # waiting, not an error
        assert files["b.pdf"].retry_count == 0
        balance = client.credits.balance()
        assert balance.daily == 0 and balance.grace == pytest.approx(0.04)
        assert run.credits_charged == 2.0  # b's first page was read and paid for, and is kept
        assert run.files_failed == 0 and run.files_processed == 1
        assert b.exists() and a.exists()

        time.next_day()
        again = client.index.run()
        assert again.status is IndexRunStatus.COMPLETED and again.files_processed == 1
        assert again.credits_charged == 1.0  # only b's second page
        files = {f.name: f.index for f in client.sources.list_files(source.id, detailed=True)}
        assert files["b.pdf"].status is FileStatus.INDEXED and files["b.pdf"].pages == 2

    def test_the_grace_covers_a_little_more(self, client, root):
        policy(client, wallets={"local": {"daily": 100, "starter": 0}}, grace_percent=2)
        write(root, "a.pdf", *[scan(f"page number {n}") for n in range(1, 103)])
        client.sources.create(root)
        run = client.index.run(workers=0)  # 100 + 2 of grace = 102 pages
        assert run.status is IndexRunStatus.COMPLETED
        balance = client.credits.balance()
        assert (balance.daily, balance.grace) == (0, 0)

    def test_grace_is_spent_last_and_free(self, client, root, time):
        policy(client, wallets={"local": {"daily": 1, "starter": 0}}, grace_percent=100)
        write(root, "a.pdf", scan("one"), scan("two"))
        client.sources.create(root)
        assert client.index.run().status is IndexRunStatus.COMPLETED
        time.next_day()
        assert client.credits.balance().daily == 1  # not deducted: grace_mode is free

    def test_native_files_wait_too_once_the_run_is_paused(self, client, root):
        policy(client, wallets={"local": {"daily": 0, "starter": 0}}, grace_percent=0)
        write(root, "a.pdf", scan())
        client.sources.create(root)
        assert client.index.run().status is IndexRunStatus.WAITING_CREDITS

    def test_a_paused_run_is_not_a_failure_for_the_next_one(self, client, root, time):
        policy(client, wallets={"local": {"daily": 0, "starter": 0}}, grace_percent=0)
        write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        (run,) = client.index.history()
        assert run.status is IndexRunStatus.WAITING_CREDITS
        policy(client, wallets={"local": {"daily": 5, "starter": 0}})
        time.next_day()
        assert client.index.run().status is IndexRunStatus.COMPLETED

    def test_in_parallel_the_credits_are_not_spent_twice(self, client, root):
        policy(client, wallets={"local": {"daily": 3, "starter": 0}}, grace_percent=0)
        for n in range(6):
            write(root, f"{n}.pdf", scan(f"unique words for file {n}"))
        source = client.sources.create(root)
        run = client.index.run(workers=4)
        assert run.status is IndexRunStatus.WAITING_CREDITS
        assert run.credits_charged == 3.0 and client.credits.balance().total == 0
        done = [f for f in client.sources.list_files(source.id, detailed=True)
                if f.index.status is FileStatus.INDEXED]  # fmt: skip
        assert len(done) == 3


class TestEstimate:
    def test_what_a_run_would_cost(self, client, root):
        write(root, "a.pdf", scan("one"), scan("two"), fp.native_page())
        write(root, "b.pdf", fp.native_page("only native words in this one"))
        client.sources.create(root)
        estimate = client.credits.estimate()
        assert (estimate.files, estimate.pages, estimate.ocr_pages) == (2, 4, 2)
        assert (estimate.credits, estimate.maximum, estimate.affordable) == (2.0, 2.5, True)
        assert json.loads(estimate.to_json()) == estimate.to_dict()

    def test_it_matches_what_a_run_charges(self, client, root):
        write(root, "a.pdf", scan("one", **fp.A3), fp.mixed_page("Native text enough words.", "x"))
        client.sources.create(root)
        estimate = client.credits.estimate()
        assert client.index.run().credits_charged == estimate.credits

    def test_nothing_is_left_to_estimate_after_a_run(self, client, root):
        write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        assert client.credits.estimate().credits == 0

    def test_duplicates_are_not_counted(self, client, root):
        write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        other = root.parent / "other"
        other.mkdir()
        write(other, "copy.pdf", scan())
        client.sources.create(other)
        assert client.credits.estimate(other).credits == 0

    def test_it_says_when_it_is_not_affordable(self, client, root):
        policy(client, wallets={"local": {"daily": 1, "starter": 0}}, grace_percent=0)
        write(root, "a.pdf", scan("one"), scan("two"))
        client.sources.create(root)
        assert not client.credits.estimate().affordable

    def test_a_single_file_and_a_source(self, client, root):
        a = write(root, "a.pdf", scan("one"))
        write(root, "b.pdf", scan("two"))
        source = client.sources.create(root)
        assert client.credits.estimate(a).files == 1
        assert client.credits.estimate(source.id).files == 2

    def test_unreadable_files_and_big_pages_cost_nothing_to_estimate(self, client, root):
        write(root, "bad.pdf", scan(), error="boom")
        write(root, "big.pdf", scan(width=9000, height=9000))
        client.sources.create(root)
        estimate = client.credits.estimate()
        assert estimate.credits == 0


class TestHistory:
    @pytest.fixture
    def busy(self, client, root):
        write(root, "a.pdf", scan("one"), scan("two"))
        write(root, "b.pdf", scan("three"))
        source = client.sources.create(root)
        run = client.index.run(workers=0)
        return source, run

    def test_newest_first_by_default(self, client, busy):
        entries = client.credits.history()
        assert all(isinstance(e, CreditEntry) for e in entries)
        assert [e.id for e in entries] == sorted((e.id for e in entries), reverse=True)

    def test_filters(self, client, busy):
        source, run = busy
        assert len(client.credits.history(kind="charge")) == 3
        assert len(client.credits.history(source=source.id)) == 3
        assert len(client.credits.history(run_id=run.id, kind=CreditEntryKind.CHARGE)) == 3
        assert client.credits.history(source=999) == []
        assert client.credits.history(kind="expire") == []

    def test_time_window(self, client, busy, time):
        now = time.now
        assert len(client.credits.history(since=now - timedelta(hours=1), kind="charge")) == 3
        assert client.credits.history(since=now + timedelta(hours=1)) == []
        assert client.credits.history(until=now - timedelta(days=1)) == []
        assert len(client.credits.history(until=now.isoformat(), kind="charge")) == 3
        naive = (now - timedelta(hours=1)).replace(tzinfo=None)
        assert len(client.credits.history(since=naive, kind="charge")) == 3

    def test_sorting_and_paging(self, client, busy):
        ascending = client.credits.history(order=SortOrder.ASC, sort_by=CreditSortBy.AT)
        assert [e.id for e in ascending] == sorted(e.id for e in ascending)
        by_amount = client.credits.history(sort_by="amount_milli", order="desc", limit=1)
        assert by_amount[0].amount == 2000  # the starter
        assert len(client.credits.history(limit=2, offset=1)) == 2

    def test_bad_values(self, client, busy):
        for kwargs, error in (
            ({"kind": "nope"}, ValueError),
            ({"sort_by": "nope"}, ValueError),
            ({"order": "sideways"}, ValueError),
            ({"since": "yesterday"}, ValueError),
            ({"since": 5}, TypeError),
            ({"limit": -1}, ValueError),
        ):
            with pytest.raises(error):
                client.credits.history(**kwargs)

    def test_dict_and_json(self, client, busy):
        entry = client.credits.history(kind="charge")[0]
        assert entry.to_dict()["kind"] == "charge"
        assert json.loads(entry.to_json()) == entry.to_dict()

    def test_purging_a_source_deletes_what_was_spent_for_it_but_not_the_balance(self, client, busy):
        source, _ = busy
        before = client.credits.balance().daily
        client.sources.remove(source.id)
        client.sources.purge(source.id)
        assert client.credits.history(kind="charge") == []
        assert client.credits.balance().daily == before == 497


class TestRedeem:
    def grants(self, *items):
        return list(items)

    def test_a_grant_is_added_once(self, client):
        first = client.credits.redeem([{"id": "LIC-1", "amount": 100}])
        assert [(g.id, g.credits, g.added) for g in first] == [("LIC-1", 100.0, True)]
        again = client.credits.redeem([{"id": "LIC-1", "amount": 100}])
        assert [(g.credits, g.added) for g in again] == [(0.0, False)]
        assert client.credits.balance().one_off == 2100

    def test_it_takes_objects_too(self, client):
        from types import SimpleNamespace

        grant = SimpleNamespace(id="LIC-2", amount=40.0, scope=None, expires=None)
        done = client.credits.redeem([grant])
        assert done[0].added and client.credits.balance().one_off == 2040

    def test_a_scoped_grant_is_not_general_credit(self, client):
        client.credits.redeem([{"id": "S", "amount": 50, "scope": "telugu"}])
        assert client.credits.balance().one_off == 2000
        entry = client.credits.history(kind="grant", limit=1)[0]
        assert entry.note == "licence (telugu)"

    def test_a_grant_scoped_to_an_addon_with_a_wallet_tops_that_wallet_up(self, client):
        pytest.importorskip("vethuq_addon_semantic")
        (done,) = client.credits.redeem([{"id": "S", "amount": 50, "scope": "semantic"}])
        assert done.added and done.credits == 50
        assert client.credits.balance().one_off == 2000  # not the local wallet's
        wallet = client.credits.balance("semantic")
        assert (wallet.one_off, wallet.daily) == (50, 50)
        entries = client.credits.history(kind="grant", wallet="semantic")
        entry = next(e for e in entries if e.note == "licence")
        assert (entry.wallet, entry.amount) == ("semantic", 50)
        (again,) = client.credits.redeem([{"id": "S", "amount": 50, "scope": "semantic"}])
        assert not again.added and client.credits.balance("semantic").one_off == 50

    def test_one_off_credits_are_spent_after_the_day_and_before_grace(self, client, root):
        policy(client, wallets={"local": {"daily": 1, "starter": 0}})
        client.credits.redeem([{"id": "T", "amount": 10}])
        write(root, "a.pdf", scan("one"), scan("two"), scan("three"))
        client.sources.create(root)
        client.index.run(workers=0)
        balance = client.credits.balance()
        assert (balance.daily, balance.one_off, balance.grace) == (0, 8, pytest.approx(0.02))

    def test_a_grant_expires(self, client, time):
        expires = (time.now + timedelta(days=2)).isoformat()
        client.credits.redeem([{"id": "E", "amount": 30, "expires_at": expires}])
        assert client.credits.balance().one_off == 2030
        time.advance(days=3)
        assert client.credits.balance().one_off == 2000
        assert client.credits.history(kind="expire", limit=1)[0].amount == 30

    def test_the_default_expiry_comes_from_the_policy(self, client, time):
        policy(client, caps={"one_off_expiry_days": 10})
        client.credits.redeem([{"id": "E", "amount": 30}])
        time.advance(days=11)
        assert client.credits.balance().one_off == 2000

    def test_the_most_held_is_capped(self, client):
        policy(client, caps={"one_off_max": 2100})
        (done,) = client.credits.redeem([{"id": "A", "amount": 500}])
        assert done.credits == 100  # clipped to the room left
        with pytest.raises(errors.InvalidGrantError, match="most one-off"):
            client.credits.redeem([{"id": "B", "amount": 5}])

    @pytest.mark.parametrize(
        "grant",
        [
            {"amount": 5},
            {"id": "", "amount": 5},
            {"id": "x", "amount": 0},
            {"id": "x", "amount": -3},
            {"id": "x", "amount": "5"},
            {"id": "x", "amount": 5, "expires_at": "2020-01-01T00:00:00Z"},
            {"id": "x", "amount": 5, "expires_at": "not a date"},
        ],
    )
    def test_bad_grants_are_refused(self, client, grant):
        with pytest.raises(errors.InvalidGrantError):
            client.credits.redeem([grant])

    def test_a_bad_grant_adds_none_of_the_batch(self, client):
        with pytest.raises(errors.InvalidGrantError):
            client.credits.redeem([{"id": "ok", "amount": 5}, {"id": "bad", "amount": 0}])
        assert client.credits.balance().one_off == 2000

    @staticmethod
    def entitlements(monkeypatch, licence, seen=None):
        import sys
        from types import ModuleType, SimpleNamespace

        class Licences:
            def verify(self, token, revoked=()):
                if seen is not None:
                    seen["token"], seen["revoked"] = token, list(revoked)
                return licence

        module = ModuleType("vethuq_entitlements")
        module.Licences = Licences
        monkeypatch.setitem(sys.modules, "vethuq_entitlements", module)
        return SimpleNamespace

    def test_a_licence_is_verified_and_redeemed(self, client, monkeypatch):
        from types import SimpleNamespace

        grant = SimpleNamespace(id="L-1", amount=75.0, scope=None, expires=None)
        licence = SimpleNamespace(ok=True, detail="", credit_grants=lambda: (grant,))
        seen = {}
        self.entitlements(monkeypatch, licence, seen)
        policy(client, revoked_licence_ids=["OLD"])
        (done,) = client.credits.redeem_licence("VQLIC1.token")
        assert done.credits == 75 and seen == {"token": "VQLIC1.token", "revoked": ["OLD"]}

    def test_a_licence_that_does_not_verify_is_refused(self, client, monkeypatch):
        from types import SimpleNamespace

        self.entitlements(monkeypatch, SimpleNamespace(ok=False, detail="it has expired"))
        with pytest.raises(errors.InvalidGrantError, match="expired"):
            client.credits.redeem_licence("x")
        assert client.credits.balance().one_off == 2000

    def test_without_entitlements_it_says_so(self, client, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "vethuq_entitlements", None)
        with pytest.raises(errors.InvalidGrantError, match="vethuq-entitlements"):
            client.credits.redeem_licence("x")


class TestSpendOrder:
    def test_promotional_then_daily_then_scoped_then_general_then_grace(self, client, root):
        policy(
            client,
            wallets={"local": {"daily": 2, "starter": 0}},
            promotions=[
                {
                    "id": "p",
                    "name": "P",
                    "start_date": "2026-10-12",
                    "end_date": "2026-10-12",
                    "uplift": {"local": {"absolute": 1}},
                }
            ],
            grace_percent=50,
        )
        client.credits.redeem([{"id": "g", "amount": 1}, {"id": "s", "amount": 5, "scope": "x"}])
        write(root, "a.pdf", *[scan(f"page {n}") for n in range(1, 6)])
        client.sources.create(root)
        client.index.run(workers=0)
        spent = [e for e in client.credits.history(kind="charge", order="asc")]
        with client._db().session() as session:
            kinds = [
                g.kind.value
                for g in session.scalars(select(_CreditGrant).order_by(_CreditGrant.id))
            ]
        assert len(spent) == 5 and "promo" in kinds
        balance = client.credits.balance()
        # 1 promotional + 2 daily + 1 general one-off + 1 of the 1 grace: all gone but the scoped
        assert (balance.promotional, balance.daily, balance.one_off, balance.grace) == (0, 0, 0, 0)


class TestGrantsAndUsage:
    def test_grants_list_the_allowance_the_starter_and_a_promotion_by_name(self, client, time):
        policy(
            client,
            promotions=[
                {
                    "id": "week",
                    "name": "Launch week",
                    "start_date": "2026-10-12",
                    "end_date": "2026-10-12",
                    "uplift": {"local": {"percent": 50}},
                }
            ],
        )
        client.credits.balance()
        grants = client.credits.grants()
        kinds = {grant.kind for grant in grants}
        assert {"daily", "promo", "one_off"} <= kinds
        promo = next(grant for grant in grants if grant.kind == "promo")
        assert promo.name == "Launch week" and promo.amount == 250 and not promo.expired
        assert [g.kind for g in client.credits.grants(kind="promo")] == ["promo"]
        with pytest.raises(ValueError):
            client.credits.grants(kind="bundle")

    def test_a_spent_grant_shows_what_was_used(self, client, root):
        write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        daily = client.credits.grants(kind="daily")[0]
        assert (daily.used, daily.remaining) == (1.0, daily.amount - 1.0)

    def test_expired_grants_can_be_left_out(self, client, time):
        client.credits.balance()
        time.next_day()
        client.credits.balance()
        every = client.credits.grants(kind="daily")
        current = client.credits.grants(kind="daily", include_expired=False)
        assert len(every) == 2 and len(current) == 1 and every[1].expired

    def test_the_ledger_names_the_file(self, client, root):
        path = write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        (charge,) = client.credits.history(kind=CreditEntryKind.CHARGE)
        assert charge.file == str(path)

    def test_usage_by_day_source_and_file(self, client, root, time):
        path = write(root, "a.pdf", scan(), scan("another scanned page of words"))
        client.sources.create(root)
        client.index.run()
        (day,) = client.credits.usage("day")
        assert (day.key, day.credits, day.pages) == ("2026-10-12", 2.0, 2)
        (by_source,) = client.credits.usage("source")
        assert (by_source.key, by_source.credits) == ("1", 2.0)
        (by_file,) = client.credits.usage("file", source=1)
        assert (by_file.key, by_file.credits, by_file.pages) == (str(path), 2.0, 2)
        assert client.credits.usage("day", wallet="local")[0].credits == 2.0
        assert client.credits.usage("day", since="2026-10-13") == []
        with pytest.raises(ValueError):
            client.credits.usage("week")
        with pytest.raises(ValueError):
            client.credits.usage("day", sort_by="colour")

    def test_a_refund_comes_off_the_file(self, client, root):
        write(root, "a.pdf", scan())
        client.sources.create(root)
        client.index.run()
        ledger = client._credit_engine()
        with client._db().session() as session:
            ids = [r.id for r in client.credits.history(kind=CreditEntryKind.CHARGE)]
            ledger.wallet_for("local").refund(session, ids)
        (by_file,) = client.credits.usage("file")
        assert by_file.credits == 0.0

    def test_a_wallet_can_be_named_when_the_day_is_new(self, client, time):
        time.next_day()
        assert client.credits.grants(wallet="local")
        assert client.credits.history(wallet="local") is not None
