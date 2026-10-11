"""An add-on's own credits: its sub-wallet, as `Host.credits`."""

from __future__ import annotations

import pytest
from sqlalchemy import text

import vethuq
from vethuq._addons.host import _Host
from vethuq._credits import _Terms
from vethuq_addon_api import Credits, CreditsExhaustedError


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(tmp_path / "db" / "vethuq.db") as client:
        client.sources.list()
        yield client


@pytest.fixture
def host(client):
    return _Host("semantic", client.db_path, lambda: None, credits=client._credit_engine)


def ledger(client, wallet):
    with client._db().session() as session:
        return session.execute(
            text("SELECT kind, amount_milli, phase, note FROM credit_ledger WHERE wallet = :w"),
            {"w": wallet},
        ).all()


class TestTerms:
    def test_semantic_has_a_baseline_wallet_and_price(self):
        terms = _Terms()
        assert terms.semantic == 0.5 and terms.rate_for("semantic", 9) == 0.5
        assert terms.daily_for("semantic") == 50.0 and terms.starter_for("semantic") == 0.0

    def test_other_addons_have_nothing_until_a_licence_grants_it(self):
        terms = _Terms()
        assert terms.daily_for("translate") == 0.0 and terms.starter_for("translate") == 0.0
        assert terms.rate_for("translate", 2.0) == 2.0

    def test_the_policy_sets_the_price_and_the_allowances(self):
        policy = {
            "rate_card": {"version": 2, "semantic": 0.75},
            "wallets": {
                "addons": {
                    "semantic": {"local_daily": 80, "starter": 20},
                    "translate": {"local_daily": 5},
                }
            },
        }
        terms = _Terms.from_policy(policy)
        assert terms.rate_for("semantic", 0) == 0.75
        assert (terms.daily_for("semantic"), terms.starter_for("semantic")) == (80.0, 20.0)
        assert (terms.daily_for("translate"), terms.starter_for("translate")) == (5.0, 0.0)

    def test_a_policy_without_them_keeps_the_baseline(self):
        terms = _Terms.from_policy({"wallets": {"addons": "nonsense"}})
        assert terms.daily_for("semantic") == 50.0
        assert _Terms.from_policy({}).addon_wallets == _Terms().addon_wallets

    def test_the_terms_survive_being_stored_for_the_day(self):
        terms = _Terms.from_policy({"wallets": {"addons": {"semantic": {"local_daily": 7}}}})
        assert _Terms.from_dict(terms.to_dict()).daily_for("semantic") == 7.0


class TestCredits:
    def test_the_host_has_credits(self, host):
        assert isinstance(host.credits, Credits)

    def test_a_host_without_a_credit_service_has_nothing_to_spend(self, tmp_path):
        credits = _Host("x", tmp_path / "v.db", lambda: None).credits
        assert credits.balance_milli() == 0 and credits.rate("semantic", 0.5) == 0.5
        credits.charge(0)
        with pytest.raises(CreditsExhaustedError):
            credits.charge(1)

    def test_the_wallet_starts_with_its_daily_allowance(self, host, client):
        assert host.credits.rate("semantic", 0.0) == 0.5
        balance = client.credits.balance("semantic")
        assert (balance.daily, balance.one_off) == (50.0, 0.0)
        assert host.credits.balance_milli() == balance.total * 1000  # the grace included

    def test_a_charge_comes_off_the_addons_wallet_and_nothing_else(self, host, client):
        local = client.credits.balance("local").total
        before = host.credits.balance_milli()
        host.credits.charge(1500, note="semantic: 3 pages")
        assert host.credits.balance_milli() == before - 1500
        assert client.credits.balance("local").total == local
        (row,) = (r for r in ledger(client, "semantic") if r.kind == "charge")
        assert (row.amount_milli, row.phase, row.note) == (1500, "semantic", "semantic: 3 pages")

    def test_it_cannot_spend_more_than_it_has(self, host, client):
        everything = host.credits.balance_milli()
        host.credits.charge(everything)
        assert host.credits.balance_milli() == 0
        with pytest.raises(CreditsExhaustedError) as caught:
            host.credits.charge(1)
        assert "credits" in str(caught.value) and caught.value.hint
        assert host.credits.balance_milli() == 0

    def test_a_failed_charge_spends_nothing(self, host):
        before = host.credits.balance_milli()
        with pytest.raises(CreditsExhaustedError):
            host.credits.charge(before + 1)
        assert host.credits.balance_milli() == before

    def test_a_charge_is_whole_milli_credits(self, host):
        for bad in (-1, 1.5, True, "2"):
            with pytest.raises(ValueError, match="milli-credits"):
                host.credits.charge(bad)

    def test_ocr_credits_cannot_pay_for_it_and_it_cannot_pay_for_ocr(self, host, client):
        local_before = client.credits.balance("local").total
        host.credits.charge(host.credits.balance_milli())
        assert client.credits.balance("local").total == local_before
        with pytest.raises(CreditsExhaustedError):
            host.credits.charge(1)

    def test_two_addons_have_separate_wallets(self, client):
        a = _Host("semantic", client.db_path, lambda: None, credits=client._credit_engine)
        b = _Host("translate", client.db_path, lambda: None, credits=client._credit_engine)
        assert b.credits.balance_milli() == 0
        a.credits.charge(1000)
        assert b.credits.balance_milli() == 0

    def test_the_metrics_bonus_does_not_reach_it(self, client):
        # The bonus is for the local and GitHub wallets only (docs/credits.md, section 3).
        assert "semantic" not in client._credit_engine().BONUS_WALLETS

    def test_a_licence_grant_could_fund_another_wallet(self, client):
        service = client._credit_engine()
        with client._db().session() as session:
            service.sync(session, "translate")
            service.wallet_for("translate").add_one_off(
                session, "grant:x", 3000, "licence", scope=None, expires=None
            )
        host = _Host("translate", client.db_path, lambda: None, credits=client._credit_engine)
        assert host.credits.balance_milli() == 3000
        host.credits.charge(2000)
        assert host.credits.balance_milli() == 1000


class TestPublicWallets:
    def test_an_installed_addon_with_a_wallet_is_listed(self, client):
        pytest.importorskip("vethuq_addon_semantic")
        assert client.credits.wallets() == ["local", "semantic"]
        balance = client.credits.balance("semantic")
        assert (balance.wallet, balance.daily_allowance) == ("semantic", 50.0)
        assert client.credits.balance("local").bonus_active is False

    def test_the_ledger_can_be_read_per_wallet(self, host, client):
        pytest.importorskip("vethuq_addon_semantic")
        host.credits.charge(500, note="semantic: 1 pages")
        (entry,) = client.credits.history(kind="charge", wallet="semantic")
        assert (entry.wallet, entry.amount) == ("semantic", 0.5)


class TestDataDir:
    def test_each_addon_gets_a_folder_of_its_own_beside_the_database(self, host, client, tmp_path):
        folder = host.data_dir()
        assert folder.is_dir() and folder.name == "semantic" and folder.parent.name == "addons"
        assert folder.parent.parent == tmp_path  # the data root: db/ is inside it
        other = _Host("other", client.db_path, lambda: None).data_dir()
        assert other != folder

    def test_it_moves_with_the_data_root(self, host):
        from vethuq._paths import _Paths

        assert _Paths.ADDONS_DIRNAME in _Paths._DATA_DIRNAMES

    @pytest.mark.parametrize("bad", ["", "..", "a/b", "a\\b", "."])
    def test_an_id_that_is_not_one_is_refused(self, client, bad):
        with pytest.raises(ValueError, match="isn't an add-on id"):
            _Host(bad, client.db_path, lambda: None).data_dir()
