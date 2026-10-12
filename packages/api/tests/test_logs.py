from __future__ import annotations

import logging

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.logs_service import LogsService

BASE = {"day": None, "level": None, "contains": None, "order": "asc", "limit": 100, "after": None}


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    log = instance.logs.cli.logger()
    for number in range(30):
        log.info("step %s of the work", number)
    log.warning("something odd happened")
    try:
        raise RuntimeError("it broke")
    except RuntimeError:
        log.exception("a failure")
    for handler in log.handlers:
        handler.flush()
    yield instance
    instance.close()


@pytest.fixture
def service(vethuq):
    return LogsService(lambda: vethuq)


class TestFiles:
    def test_every_component_is_listed_with_what_it_logs(self, service):
        names = {c["component"]: c for c in service.components()}
        assert {"cli", "index", "database", "ui", "policy"} <= set(names)
        assert names["cli"]["exists"] and names["cli"]["description"]
        assert names["index"]["exists"] is False
        assert service.days("cli") and service.days("index") == []


class TestEntries:
    def test_the_latest_entries_come_last_and_the_total_is_given(self, service):
        data = service.entries("cli", **{**BASE, "limit": 5})
        assert data["total"] >= 32 and len(data["items"]) == 5
        assert data["offset"] == data["total"] - 5
        assert data["items"][-1]["level"] == "error"
        assert "RuntimeError" in data["items"][-1]["message"]  # the traceback is with it

    def test_newest_first_starts_at_the_top(self, service):
        data = service.entries("cli", **{**BASE, "order": "desc", "limit": 2})
        assert data["offset"] == 0 and data["items"][0]["message"].startswith("a failure")

    def test_level_and_text_filters(self, service):
        warnings = service.entries("cli", **{**BASE, "level": "warning"})
        assert [e["level"] for e in warnings["items"]] == ["warning", "error"]
        text = service.entries("cli", **{**BASE, "contains": "STEP 7 "})
        assert [e["message"] for e in text["items"]] == ["step 7 of the work"]

    def test_following_asks_for_what_came_after(self, service, vethuq):
        first = service.entries("cli", **BASE)
        log = vethuq.logs.cli.logger()
        log.info("a later entry")
        for handler in log.handlers:
            handler.flush()
        more = service.entries("cli", **{**BASE, "after": first["total"]})
        assert [e["message"] for e in more["items"]] == ["a later entry"]
        assert more["offset"] == first["total"] and more["total"] == first["total"] + 1
        assert service.entries("cli", **{**BASE, "after": more["total"]})["items"] == []

    def test_a_component_with_no_log_is_empty_not_an_error(self, service):
        data = service.entries("index", **BASE)
        assert data == {"total": 0, "offset": 0, "items": [], "exists": False}

    def test_bad_values_are_refused(self, service):
        with pytest.raises(ValueError):
            service.entries("cli", **{**BASE, "level": "loud"})
        with pytest.raises(ValueError):
            service.entries("cli", **{**BASE, "order": "up"})


class TestExport:
    def test_what_is_filtered_is_what_is_written(self, service):
        data, name = service.export("cli", day=None, level="warning", contains=None, order="asc")
        text = data.decode()
        assert name.startswith("cli-") and name.endswith(".log")
        assert "something odd happened" in text and "step 3 " not in text


class TestHttp:
    @pytest.fixture
    def http(self, web_dist, tmp_path):
        core = VethuQCore(tmp_path / "vethuq.db")
        log = core._vethuq().logs.cli.logger()
        log.info("hello from the test")
        for handler in log.handlers:
            handler.flush()
        app = create_app(bootstrap_token="t", web_dist=web_dist, core=core)
        allow_host(app, "127.0.0.1:5000")
        client = app.test_client()
        client.get("/?t=t", base_url=ORIGIN)
        logging.getLogger("vethuq.cli")
        return client

    def test_the_endpoints_answer(self, http):
        listing = http.get("/api/logs", base_url=ORIGIN).get_json()
        assert any(c["component"] == "cli" for c in listing["components"])
        entries = http.get("/api/logs/cli?limit=10&level=info", base_url=ORIGIN).get_json()
        assert any("hello from the test" in e["message"] for e in entries["items"])
        followed = http.get(f"/api/logs/cli?after={entries['total']}", base_url=ORIGIN)
        assert followed.get_json()["items"] == []
        export = http.get("/api/logs/cli/export?contains=hello", base_url=ORIGIN)
        assert "attachment" in export.headers["Content-Disposition"]
        assert b"hello from the test" in export.data

    def test_bad_requests_are_refused(self, http):
        assert http.get("/api/logs/cli?level=loud", base_url=ORIGIN).status_code == 422
        assert http.get("/api/logs/cli?limit=x", base_url=ORIGIN).status_code == 422
        assert http.get("/api/logs/nothing", base_url=ORIGIN).status_code in (404, 422)
