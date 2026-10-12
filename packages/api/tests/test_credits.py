from __future__ import annotations

import json

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq._db import _CreditLedger
from vethuq._db.values import _LedgerKind
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.credits_service import CreditsService

HEADERS = {"Origin": ORIGIN}


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


@pytest.fixture
def service(vethuq):
    return CreditsService(lambda: vethuq)


def spend(
    vethuq, source_id, path, milli, pages=1, kind=_LedgerKind.CHARGE, at="2026-10-12T10:00:00+00:00"
):
    """Write ledger rows as an OCR run would, without needing a scanned page."""
    with vethuq._db().session() as session:
        for page in range(1, pages + 1):
            session.add(
                _CreditLedger(
                    at=at,
                    wallet="local",
                    kind=kind,
                    amount_milli=milli,
                    source_id=source_id,
                    run_id=1,
                    page_number=page,
                    phase="quick",
                    language="en",
                    note=path,
                )
            )


@pytest.fixture
def with_work(vethuq, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.pdf").write_text("x")
    source = vethuq.sources.create(folder)
    spend(vethuq, source.id, str(folder / "a.pdf"), 1000, pages=2)
    spend(vethuq, source.id, str(folder / "b.pdf"), 500, at="2026-10-13T10:00:00+00:00")
    return source


class TestBalances:
    def test_each_wallet_shows_today_and_the_status_bar_summary(self, service):
        local = next(w for w in service.wallets() if w["wallet"] == "local")
        assert local["wallet"] == "local"
        assert local["daily_used"] == round(local["daily_allowance"] - local["daily"], 3)
        summary = service.summary()
        assert summary["primary"] == "local" and summary["level"] == "ok"
        assert summary["daily"] == local["daily"]

    def test_totals_add_up(self, service, with_work):
        totals = service.totals("local")
        assert totals["consumed"] == 2.5
        assert totals["received"] > 0 and totals["remaining"] > 0

    def test_the_summary_warns_when_little_is_left(self, service, vethuq):
        balance = vethuq.credits.balance()
        spend(vethuq, None, "x", 1)
        with vethuq._db().session() as session:
            from vethuq._db import _CreditGrant

            for grant in session.query(_CreditGrant).filter_by(kind="daily"):
                grant.remaining_milli = int(grant.amount_milli * 0.1)
        summary = service.summary()
        assert summary["level"] == "low" and balance.daily > summary["daily"]


class TestLists:
    def test_grants_filter_sort_and_search(self, service):
        args = {
            "wallet": None,
            "kind": None,
            "scope": None,
            "include_expired": True,
            "q": "",
            "sort": "granted_at",
            "order": "desc",
            "offset": 0,
            "limit": 50,
        }
        everything = service.grants(**args)
        assert everything["total"] >= 2
        kinds = {g["kind"] for g in everything["items"]}
        assert {"daily", "one_off"} <= kinds
        only = service.grants(**{**args, "kind": "one_off"})
        assert {g["kind"] for g in only["items"]} == {"one_off"}
        by_amount = service.grants(**{**args, "sort": "amount", "order": "asc"})["items"]
        assert [g["amount"] for g in by_amount] == sorted(g["amount"] for g in by_amount)
        with pytest.raises(ValueError):
            service.grants(**{**args, "sort": "colour"})

    def test_usage_by_day_source_and_file(self, service, with_work):
        base = {
            "wallet": None,
            "source": None,
            "since": None,
            "until": None,
            "q": "",
            "sort": "key",
            "order": "asc",
            "offset": 0,
            "limit": 50,
        }
        days = service.usage(group_by="day", **base)
        assert [(d["key"], d["credits"]) for d in days["items"]] == [
            ("2026-10-12", 2.0),
            ("2026-10-13", 0.5),
        ]
        assert days["credits"] == 2.5
        (by_source,) = service.usage(group_by="source", **base)["items"]
        assert (by_source["name"], by_source["credits"]) == ("docs", 2.5)
        files = service.usage(group_by="file", **{**base, "sort": "credits", "order": "desc"})[
            "items"
        ]
        assert [(f["name"], f["credits"], f["source"]) for f in files] == [
            ("a.pdf", 2.0, "docs"),
            ("b.pdf", 0.5, "docs"),
        ]
        assert [
            f["name"] for f in service.usage(group_by="file", **{**base, "q": "b.pdf"})["items"]
        ] == ["b.pdf"]

    def test_the_daily_chart_fills_empty_days(self, service, with_work):
        data = service.daily(7)
        assert "local" in data["wallets"] and len(data["days"]) == 7
        assert all(w in day for day in data["days"] for w in data["wallets"])

    def test_the_ledger_pages_and_names_files(self, service, with_work):
        args = {
            "kind": "charge",
            "wallet": None,
            "source": None,
            "run": None,
            "since": None,
            "until": None,
            "sort": "amount",
            "order": "desc",
            "offset": 0,
            "limit": 2,
        }
        page = service.ledger(**args)
        assert len(page["items"]) == 2 and page["more"] is True
        assert page["items"][0]["file"].endswith("a.pdf")
        assert service.ledger(**{**args, "offset": 2})["more"] is False


class TestExports:
    def test_csv_and_json(self, service):
        rows = [{"a": 1, "b": "x"}]
        data, name, mime = service.export(rows, "csv", "credits-grants")
        assert data.decode("utf-8-sig").splitlines() == ["a,b", "1,x"] and name.endswith(".csv")
        data, _, mime = service.export(rows, "json", "x")
        assert json.loads(data) == rows and mime == "application/json"
        with pytest.raises(ValueError):
            service.export(rows, "pdf", "x")


class TestHttp:
    @pytest.fixture
    def http(self, web_dist, tmp_path):
        app = create_app(
            bootstrap_token="t", web_dist=web_dist, core=VethuQCore(tmp_path / "vethuq.db")
        )
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        return client

    def test_the_endpoints_answer(self, http):
        summary = http.get("/api/credits/summary", base_url=ORIGIN).get_json()
        assert summary["primary"] == "local"
        wallets = http.get("/api/credits/wallets", base_url=ORIGIN).get_json()
        assert wallets["totals"][0]["wallet"] == "local"
        grants = http.get("/api/credits/grants?kind=daily&expired=0", base_url=ORIGIN).get_json()
        assert {g["kind"] for g in grants["items"]} == {"daily"}
        assert (
            http.get("/api/credits/usage?group_by=file", base_url=ORIGIN).get_json()["items"] == []
        )
        assert (
            http.get("/api/credits/daily?days=3", base_url=ORIGIN).get_json()["days"].__len__() == 3
        )
        assert "items" in http.get("/api/credits/ledger?kind=grant", base_url=ORIGIN).get_json()

    def test_bad_values_are_refused_and_exports_download(self, http):
        assert http.get("/api/credits/grants?kind=bundle", base_url=ORIGIN).status_code == 422
        assert http.get("/api/credits/usage?group_by=week", base_url=ORIGIN).status_code == 422
        assert http.get("/api/credits/ledger?limit=x", base_url=ORIGIN).status_code == 422
        assert http.get("/api/credits/export/nothing", base_url=ORIGIN).status_code == 404
        response = http.get("/api/credits/export/grants?format=csv", base_url=ORIGIN)
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.data.startswith(b"\xef\xbb\xbfid,wallet") or b"wallet" in response.data

    def test_redeeming_needs_a_licence(self, http):
        refused = http.post("/api/credits/redeem", json={}, base_url=ORIGIN, headers=HEADERS)
        assert refused.status_code == 422
        bad = http.post(
            "/api/credits/redeem", json={"token": "not-a-licence"}, base_url=ORIGIN, headers=HEADERS
        )
        assert bad.status_code == 422
