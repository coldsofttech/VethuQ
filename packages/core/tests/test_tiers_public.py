from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import vethuq
from tests import fake_pipeline as fp
from tests import fake_tiers as ft
from vethuq import errors
from vethuq._credits import _Clock
from vethuq._db import _IndexRun
from vethuq._indexing import _Indexer
from vethuq.enums import IndexRunStatus, ProcessingTier
from vethuq.tiers import TierInfo, Tiers
from vethuq_addon_api import TierSpec
from vethuq_addon_api.testing import FakeExecutor


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)


@pytest.fixture
def github_addon(tmp_path_factory, monkeypatch):
    """The tier add-on, installed. Ask for it before `client`, which loads add-ons when used."""
    ft.reset()
    folder = tmp_path_factory.mktemp("tier_addon")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    ft.install(folder)
    yield ft.STATE
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.github")]:
        del sys.modules[name]


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    (folder / name).write_text(fp.pdf_document(*pages), encoding="utf-8")


class TestList:
    def test_local_is_always_there_and_hybrid_waits_for_github(self, client):
        assert isinstance(client.tiers, Tiers)
        local, hybrid = client.tiers.list()
        assert isinstance(local, TierInfo)
        assert (local.id, local.wallet, local.available, local.selected, local.remote) == (
            "local",
            "local",
            True,
            True,
            False,
        )
        assert (hybrid.id, hybrid.available) == ("hybrid", False)
        assert "needs the GitHub tier" in hybrid.reason and not hybrid.selected

    def test_an_addon_adds_its_tiers(self, github_addon, client):
        tiers = {t.id: t for t in client.tiers.list()}
        assert list(tiers) == ["local", "cloud", "github", "hybrid"]
        assert (tiers["github"].remote, tiers["github"].wallet) == (True, "github")
        assert tiers["cloud"].remote is False
        assert tiers["hybrid"].available and tiers["hybrid"].wallet == "local"

    def test_an_unavailable_tier_says_why_and_takes_hybrid_with_it(self, github_addon, client):
        github_addon.github_available, github_addon.github_reason = False, "not set up"
        tiers = {t.id: t for t in client.tiers.list()}
        assert (tiers["github"].available, tiers["github"].reason) == (False, "not set up")
        assert not tiers["hybrid"].available and "not set up" in tiers["hybrid"].reason

    def test_a_tier_without_an_executor_is_unavailable(self, github_addon, client):
        github_addon.github_executor = None
        github = client.tiers.get("github")
        assert not github.available and "no executor" in github.reason

    def test_an_addon_cannot_take_a_reserved_id(self, github_addon, client):
        github_addon.extra = [
            TierSpec("local", "Fake local", "x", FakeExecutor()),
            TierSpec("hybrid", "Fake hybrid", "x", FakeExecutor()),
        ]
        labels = {t.id: t.label for t in client.tiers.list()}
        assert labels["local"] == "Local" and labels["hybrid"] == "Hybrid"

    def test_get(self, github_addon, client):
        assert client.tiers.get(" GitHub ").id == "github"
        assert client.tiers.get("nope") is None

    def test_dict_and_json(self, client):
        tier = client.tiers.get("local")
        assert json.loads(tier.to_json()) == tier.to_dict()


class TestChoosing:
    def test_local_is_the_default(self, client):
        assert client.tiers.current().id == "local"

    def test_use_and_reset(self, github_addon, client):
        assert client.tiers.use("github").selected
        assert client.tiers.current().id == "github"
        assert [t.id for t in client.tiers.list() if t.selected] == ["github"]
        assert client.tiers.reset().id == "local"
        assert client.tiers.use(ProcessingTier.HYBRID).id == "hybrid"

    def test_the_choice_is_remembered(self, github_addon, client):
        client.tiers.use("cloud")
        with vethuq.VethuQ(db_path=client.db_path) as other:
            assert other.tiers.current().id == "cloud"

    def test_an_unknown_tier_is_refused(self, client):
        with pytest.raises(errors.TierUnavailableError, match="no processing tier"):
            client.tiers.use("github")  # no add-on
        with pytest.raises(errors.TierUnavailableError):
            client.tiers.use("nope")

    def test_an_unavailable_tier_can_be_chosen_but_not_run(self, github_addon, client, root):
        github_addon.github_available, github_addon.github_reason = False, "not set up"
        client.tiers.use("github")
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        with pytest.raises(errors.TierUnavailableError, match="not set up"):
            client.index.run()

    def test_a_removed_addon_leaves_the_default_unavailable_not_broken(
        self, github_addon, client, root
    ):
        client.tiers.use("cloud")
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        with vethuq.VethuQ(db_path=client.db_path) as other:
            manager = other._manager()
            manager._discover = lambda: []  # the add-on is gone
            manager.reload()
            assert other.tiers.current().id == "local"  # shown as local while it is gone
            with pytest.raises(errors.TierUnavailableError, match="no processing tier 'cloud'"):
                other.index.run()


class TestRunning:
    def test_local_by_default(self, client, root):
        write(root, "a.pdf", fp.scanned_page())
        client.sources.create(root)
        run = client.index.run()
        assert run.tier == "local" and run.to_dict()["tier"] == "local"
        assert len(fp.STATE.ocr_calls) == 1

    def test_naming_the_tier(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        assert client.index.run(tier="local").tier == "local"
        assert client.index.run(tier=ProcessingTier.LOCAL.value).tier == "local"
        assert client.index.history()[0].tier == "local"

    def test_an_unknown_tier_makes_no_run(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        with pytest.raises(errors.TierUnavailableError, match="Tiers: local, hybrid"):
            client.index.run(tier="nope")
        assert client.index.history() == []
        with pytest.raises(TypeError):
            client.index.run(tier=5)

    def test_hybrid_without_github(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        with pytest.raises(errors.TierUnavailableError, match="needs the GitHub tier"):
            client.index.run(tier="hybrid")

    def test_remote_tiers_cannot_run_yet(self, github_addon, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        for tier in ("github", "hybrid"):
            with pytest.raises(errors.TierUnavailableError, match="can't run in this version"):
                client.index.run(tier=tier)
        assert client.index.history() == []

    def test_wait_and_timeout_are_checked_and_ignored_locally(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        assert client.index.run(wait=True, timeout=5).status is IndexRunStatus.COMPLETED
        for bad in (0, -1, True, "5"):
            with pytest.raises(ValueError):
                client.index.run(timeout=bad)

    def test_a_synchronous_addon_tier_reads_the_pages_and_pays_its_wallet(
        self, github_addon, client, root
    ):
        write(root, "a.pdf", fp.scanned_page(), fp.scanned_page("another page of text"))
        source = client.sources.create(root)
        run = client.index.run(tier="cloud")
        assert run.tier == "cloud" and run.status is IndexRunStatus.COMPLETED
        assert fp.STATE.ocr_calls == []  # the local engine was not used
        assert [r.key for r in github_addon.cloud.seen] == ["1:0", "2:0"]
        assert all(r.language.id == "en" and r.phase == "quick" for r in github_addon.cloud.seen)
        from vethuq._db import _PdfPage

        with client._db().session() as session:
            texts = [
                p.text for p in session.scalars(select(_PdfPage).order_by(_PdfPage.page_number))
            ]
        assert texts == ["read in the cloud"] * 2
        # paid from the github wallet, not the local one
        assert client.credits.balance("local").daily == 500
        assert client.credits.balance("github").daily == 18
        assert run.credits_charged == 2.0
        assert {e.wallet for e in client.credits.history(kind="charge")} == {"github"}
        assert client.stats.overview(engine="fake-executor 1.0").total.pages == 2
        assert source.id

    def test_the_default_tier_applies_to_runs(self, github_addon, client, root):
        client.tiers.use("cloud")
        write(root, "a.pdf", fp.scanned_page())
        client.sources.create(root)
        assert client.index.run().tier == "cloud"
        assert client.index.run(tier="local").tier == "local"

    def test_an_executor_that_fails_fails_the_file_and_refunds(self, github_addon, client, root):
        class Broken(FakeExecutor):
            def recognize(self, request):
                raise RuntimeError("the cloud fell over")

        github_addon.cloud = Broken()
        write(root, "a.pdf", fp.scanned_page())
        source = client.sources.create(root)
        run = client.index.run(tier="cloud")
        assert run.files_failed == 1
        (info,) = client.sources.list_files(source.id, detailed=True)
        assert "fell over" in info.index.error
        assert client.credits.balance("github").daily == 20

    def test_waiting_for_credits_uses_the_tiers_wallet(self, github_addon, client, root):
        client._credit_engine().policy = lambda: {
            "wallets": {"github": {"daily_private": 1}}, "grace_percent": 0}  # fmt: skip
        write(root, "a.pdf", fp.scanned_page("one"), fp.scanned_page("two"))
        client.sources.create(root)
        run = client.index.run(tier="cloud", workers=0)
        assert run.status is IndexRunStatus.WAITING_CREDITS
        assert client.credits.balance("local").daily == 500  # untouched
        with client._db().session() as session:
            assert session.scalars(select(_IndexRun.tier)).one() == "cloud"


class TestWallets:
    def test_only_the_wallets_of_usable_tiers(self, client):
        assert client.credits.wallets() == ["local"]
        with pytest.raises(ValueError, match="No wallet 'github'"):
            client.credits.balance("github")
        with pytest.raises(ValueError):
            client.credits.history(wallet="github")

    def test_the_github_wallet(self, github_addon, client):
        assert client.credits.wallets() == ["local", "github"]
        balance = client.credits.balance("github")
        assert balance.wallet == "github"
        assert (balance.daily, balance.one_off, balance.grace) == (20, 0, 0.4)
        assert client.credits.balance().wallet == "local"
        assert [e.wallet for e in client.credits.history(wallet="github")] == ["github"]

    def test_the_github_amount_follows_the_repository_visibility(self, github_addon, client):
        from vethuq._credits import _Credits

        with client._db().session() as session:
            _Credits.set_github_private(session, False)
        assert client.credits.balance("github").daily == 200

    def test_the_policy_sets_the_github_wallet(self, github_addon, client):
        client._credit_engine().policy = lambda: {
            "wallets": {"github": {"daily_private": 30, "starter": 5}}}  # fmt: skip
        balance = client.credits.balance("github")
        assert (balance.daily, balance.one_off) == (30, 5)

    def test_a_promotion_for_github_only(self, github_addon, client):
        client._credit_engine().policy = lambda: {
            "promotions": [
                {
                    "id": "g", "name": "G", "start_date": "2020-01-01", "end_date": "2999-01-01",
                    "uplift": {"github": {"absolute": 10}},
                }
            ]
        }  # fmt: skip
        assert client.credits.balance("github").promotional == 10
        assert client.credits.balance("local").promotional == 0

    def test_the_metrics_bonus_reaches_the_github_wallet_too(
        self, github_addon, client, monkeypatch
    ):
        clock = [datetime(2026, 10, 12, 10, tzinfo=UTC)]
        monkeypatch.setattr(_Clock, "system", staticmethod(lambda: clock[0]))
        sent = []
        client._credit_engine().policy = lambda: {
            "metrics": {"enabled": True, "endpoint": "https://m.test"}}  # fmt: skip
        client._metrics_engine().sender = lambda url, body: sent.append(url) or (200, "{}")
        client.metrics.opt_in()
        client.credits.balance("github")
        client.metrics.send()
        clock[0] += timedelta(days=1)
        github = client.credits.balance("github")
        assert (github.bonus_active, github.bonus, github.daily_allowance) == (True, 2.0, 22.0)
        assert client.credits.balance("local").bonus == 50

    def test_add_on_wallets_get_no_daily_allowance(self, github_addon, client):
        github_addon.extra = [TierSpec("semantic", "Semantic", "semantic", FakeExecutor())]
        balance = client.credits.balance("semantic")
        assert (balance.daily, balance.one_off, balance.total) == (0, 0, 0)


class TestTierSettings:
    def test_defaults_and_changes(self, client):
        s = client.settings.tiers
        assert (s.get_min_size_factor(), s.get_phases(), s.get_wait_timeout_minutes()) == (
            2.0,
            [],
            60,
        )
        assert (s.get_max_job_pages(), s.get_max_job_megabytes()) == (200, 200)
        s.set_min_size_factor(0)
        s.set_min_size_factor(3.5)
        assert s.set_phases([" Moderate ", "deep", "deep"]) == ["moderate", "deep"]
        s.set_wait_timeout_minutes(10)
        s.set_max_job_pages(50)
        s.set_max_job_megabytes(20)
        assert (s.get_min_size_factor(), s.get_phases(), s.get_wait_timeout_minutes()) == (
            3.5,
            ["moderate", "deep"],
            10,
        )
        assert (s.get_max_job_pages(), s.get_max_job_megabytes()) == (50, 20)
        for reset in (
            s.reset_min_size_factor,
            s.reset_phases,
            s.reset_wait_timeout_minutes,
            s.reset_max_job_pages,
            s.reset_max_job_megabytes,
        ):
            reset()
        assert (s.get_min_size_factor(), s.get_phases(), s.get_wait_timeout_minutes()) == (
            2.0,
            [],
            60,
        )
        assert (s.get_max_job_pages(), s.get_max_job_megabytes()) == (200, 200)

    @pytest.mark.parametrize("value", [-1, True, "2", None])
    def test_bad_size_factors(self, client, value):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.tiers.set_min_size_factor(value)

    @pytest.mark.parametrize("value", [0, -5, 1.5, True, "9", None])
    def test_bad_counts(self, client, value):
        s = client.settings.tiers
        for setter in (s.set_wait_timeout_minutes, s.set_max_job_pages, s.set_max_job_megabytes):
            with pytest.raises(errors.InvalidSettingValueError):
                setter(value)

    @pytest.mark.parametrize("value", ["moderate", ["slow"], 5])
    def test_bad_phases(self, client, value):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.tiers.set_phases(value)

    def test_damaged_saved_values_fall_back(self, client):
        from vethuq._settings import _Settings, _TierSettings

        with client._db().session() as session:
            _Settings.set(session, _TierSettings.MIN_SIZE_KEY, "big")
            _Settings.set(session, _TierSettings.WAIT_KEY, "-3")
            _Settings.set(session, _TierSettings.JOB_PAGES_KEY, "x")
            _Settings.set(session, _TierSettings.DEFAULT_KEY, "Not A Tier!")
            _Settings.set(session, _TierSettings.PHASES_KEY, "slow,deep")
        s = client.settings.tiers
        assert (s.get_min_size_factor(), s.get_wait_timeout_minutes(), s.get_max_job_pages()) == (
            2.0,
            60,
            200,
        )
        assert s.get_phases() == ["deep"] and client.tiers.current().id == "local"
