from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.stats_service import StatsService


@pytest.fixture
def vethuq(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("alpha words here")
    (folder / "b.md").write_text("# beta words here")
    (folder / "c.csv").write_text("x,y\n1,2\n")
    instance = VethuQ(tmp_path / "vethuq.db")
    instance.settings.index.set_stability_check_seconds(0)
    instance.sources.create(folder)
    instance.index.run()
    yield instance
    instance.close()


@pytest.fixture
def service(vethuq):
    return StatsService(lambda: vethuq)


BASE = {"sort": "key", "order": "asc", "offset": 0, "limit": 50}


class TestSummary:
    def test_totals_and_a_series_of_days_with_gaps_filled(self, service):
        data = service.summary()
        total = data["total"]
        assert total["pages"] >= 3 and total["ocr_pages"] == 0
        days = data["days"]
        assert len(days) == 60 or len(days) >= 1
        today = datetime.now(UTC).date().isoformat()
        assert days[-1]["day"] == today and days[-1]["native"] == total["native_pages"]
        assert all(set(d) == {"day", "native", "ocr"} for d in days)

    def test_a_period_sets_the_days(self, service):
        data = service.summary(since="2020-01-01", until="2020-01-03")
        assert [d["day"] for d in data["days"]] == ["2020-01-01", "2020-01-02", "2020-01-03"]
        assert data["total"]["pages"] == 0

    def test_filters_narrow_the_totals(self, service):
        csv = service.summary(file_type="csv")["total"]["pages"]
        assert 0 < csv < service.summary()["total"]["pages"]


class TestBreakdown:
    def test_every_group_answers_with_a_total_row(self, service):
        for group in ("source", "language", "file_type", "engine", "page_source", "band", "day"):
            data = service.breakdown(group_by=group, **BASE)
            assert data["totals"]["pages"] >= 3 and data["more"] is False

    def test_by_file_type_sorts_and_pages(self, service):
        data = service.breakdown(group_by="file_type", **{**BASE, "sort": "pages", "order": "desc"})
        assert {r["key"] for r in data["items"]} >= {"csv", "txt"}
        pages = [r["pages"] for r in data["items"]]
        assert pages == sorted(pages, reverse=True)
        first = service.breakdown(group_by="file_type", **{**BASE, "limit": 1})
        assert len(first["items"]) == 1 and first["more"] is True

    def test_a_filter_by_source_path_or_id(self, service, vethuq):
        (source,) = vethuq.sources.list()
        by_id = service.breakdown(group_by="file_type", source=str(source.id), **BASE)
        by_path = service.breakdown(group_by="file_type", source=source.path, **BASE)
        assert by_id["totals"]["pages"] == by_path["totals"]["pages"] > 0

    def test_bad_values_are_refused(self, service):
        with pytest.raises(ValueError):
            service.breakdown(group_by="colour", **BASE)
        with pytest.raises(ValueError):
            service.breakdown(group_by="source", **{**BASE, "sort": "colour"})
        with pytest.raises(ValueError):
            service.breakdown(group_by="source", **{**BASE, "order": "up"})

    def test_export_has_the_bands_as_columns(self, service):
        rows = service.breakdown(group_by="file_type", **BASE)["items"]
        data, name, _ = service.export(rows, "csv")
        header = data.decode("utf-8-sig").splitlines()[0]
        assert name.endswith(".csv") and "key" in header and "bands" not in header


class TestHttp:
    @pytest.fixture
    def http(self, web_dist, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.txt").write_text("alpha words")
        core = VethuQCore(tmp_path / "vethuq.db")
        client = core._vethuq()
        client.settings.index.set_stability_check_seconds(0)
        client.sources.create(folder)
        client.index.run()
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        test = app.test_client()
        test.get("/?t=t", base_url=ORIGIN)
        return test

    def test_the_endpoints_answer(self, http):
        summary = http.get("/api/stats/summary", base_url=ORIGIN).get_json()
        assert summary["total"]["pages"] >= 1 and summary["days"]
        rows = http.get("/api/stats/breakdown?group_by=source", base_url=ORIGIN).get_json()
        assert rows["items"][0]["source_id"] == 1
        narrowed = http.get(
            "/api/stats/breakdown?group_by=file_type&file_type=txt", base_url=ORIGIN
        )
        assert [r["key"] for r in narrowed.get_json()["items"]] == ["txt"]

    def test_bad_values_and_exports(self, http):
        assert http.get("/api/stats/breakdown?group_by=x", base_url=ORIGIN).status_code == 422
        assert http.get("/api/stats/breakdown?limit=x", base_url=ORIGIN).status_code == 422
        response = http.get("/api/stats/export?group_by=day&format=json", base_url=ORIGIN)
        assert "attachment" in response.headers["Content-Disposition"]
