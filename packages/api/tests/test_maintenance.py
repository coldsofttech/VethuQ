from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.indexing import IndexingRefusedError
from vethuq_api.maintenance_service import MaintenanceService

HEADERS = {"Origin": ORIGIN}


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


@pytest.fixture
def service(vethuq):
    return MaintenanceService(lambda: vethuq)


def wait(service, name):
    for _ in range(300):
        state = service.tasks()[name]
        if not state["running"]:
            return state
        time.sleep(0.02)
    raise AssertionError("the task did not finish")


class TestDatabase:
    def test_no_check_yet_then_a_check_with_its_result(self, service):
        service.db_status()  # may or may not have run at start
        started = service.db_check(quick=True)
        assert started["running"]
        done = wait(service, "db-check")
        assert done["error"] is None and done["result"]["ok"] and done["result"]["quick"]
        last = service.db_status()["last"]
        assert last["ok"] is True and last["quick"] is True

    def test_a_check_runs_once_at_a_time(self, vethuq):
        gate = threading.Event()
        slow = SimpleNamespace(
            db=SimpleNamespace(
                integrity_check=lambda quick=False: (gate.wait(5), vethuq.db.integrity_check())[1]
            )
        )
        service = MaintenanceService(lambda: slow)
        service.db_check(False)
        with pytest.raises(IndexingRefusedError):
            service.db_check(False)
        gate.set()
        wait(service, "db-check")


class TestUpdatesAndPolicy:
    def test_the_update_status_and_a_check(self, service):
        status = service.updates()
        assert status["current"] and "status" in status
        assert "status" in service.updates_check(False)

    def test_the_policy_shows_where_it_came_from_and_what_it_says(self, service):
        policy = service.policy()
        assert policy["source"] == "baseline" and policy["status"] == "current"
        for key in ("versions", "notices", "features", "addons"):
            assert key in policy
        assert service.policy_refresh(False)["source"]

    def test_the_policy_is_shaped_from_what_the_core_returns(self):
        policy = SimpleNamespace(
            schema_version=1,
            sequence=4,
            kid="k",
            issued_at=None,
            versions={
                "pip": SimpleNamespace(
                    latest="2.0", minimum_supported="1.0", release_notes_url=None
                )
            },
            notices=[SimpleNamespace(id="n", message="Hello", severity="info", link=None)],
            features={"x": SimpleNamespace(enabled=False, min_client="1.5", message="Off")},
            addons={
                "github": SimpleNamespace(
                    enabled=False, latest="0.2", minimum_supported=None, message="Gone"
                )
            },
        )
        result = SimpleNamespace(
            policy=policy, to_dict=lambda: {"source": "cache", "status": "current"}
        )
        shaped = MaintenanceService._policy(result)
        assert shaped["versions"]["pip"]["latest"] == "2.0"
        assert shaped["features"]["x"] == {"enabled": False, "min_client": "1.5", "message": "Off"}
        assert shaped["addons"]["github"]["enabled"] is False and shaped["notices"][0]["id"] == "n"


class TestSearchIndex:
    def test_status_and_a_rebuild_task(self, service):
        assert service.search_index()["pages_indexed"] == 0
        service.search_rebuild()
        done = wait(service, "search-rebuild")
        assert done["error"] is None and done["result"]["pages"] == 0

    def test_a_failure_says_why(self, vethuq):
        failing = SimpleNamespace(
            search=SimpleNamespace(rebuild=lambda: SimpleNamespace(ok=False, error="disk full"))
        )
        service = MaintenanceService(lambda: failing)
        service.search_rebuild()
        assert "disk full" in wait(service, "search-rebuild")["error"]


class TestMetrics:
    def test_the_status_says_where_sharing_stands(self, service):
        status = service.metrics()
        assert (
            status["opted_in"] is False and "pending_days" in status and "bonus_percent" in status
        )

    def test_the_preview_is_the_batch_itself_with_its_size(self, service):
        data = service.metrics_preview()
        batch = data["batch"]
        assert set(batch) >= {"schema", "batch_id", "install_id", "client", "settings", "days"}
        assert data["size_bytes"] > 0
        assert "path" not in str(batch).lower()  # names and paths are never in it

    def test_sending_while_not_opted_in_sends_nothing(self, service):
        assert service.metrics_send(False)["status"] == "not_opted_in"
        assert service.metrics_send(True)["status"] == "not_opted_in"

    def test_deleting_answers_with_a_status_and_never_raises(self, service):
        assert "status" in service.metrics_delete()


class TestTiers:
    def test_they_are_listed_chosen_and_reset(self, service):
        tiers = {t["id"]: t for t in service.tiers()}
        assert tiers["local"]["selected"] is True
        assert service.tiers_use("local")["id"] == "local"
        assert service.tiers_reset()["id"] == "local"


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
        get = lambda path: http.get(f"/api{path}", base_url=ORIGIN).get_json()  # noqa: E731
        post = lambda path, **body: http.post(  # noqa: E731
            f"/api{path}", json=body, base_url=ORIGIN, headers=HEADERS
        )
        assert "last" in get("/db") and "current" in get("/updates")
        assert get("/policy")["source"] and "pages_total" in get("/search-index")
        assert get("/tiers")["tiers"][0]["id"] == "local"
        assert get("/metrics")["opted_in"] is False
        assert get("/metrics/preview")["batch"]["schema"] == 1
        assert post("/metrics/send").get_json()["status"] == "not_opted_in"
        assert "status" in post("/metrics/delete-data").get_json()
        assert post("/db/check", quick=True).status_code == 202
        assert post("/search-index/rebuild").status_code in (202, 409)
        assert set(get("/maintenance/tasks")) == {"db-check", "search-rebuild"}
        assert post("/updates/check").status_code == 200
        assert post("/policy/refresh", force=False).status_code == 200
        assert post("/tiers/use", tier="local").get_json()["id"] == "local"
        assert post("/tiers/reset").status_code == 200

    def test_bad_requests_are_refused(self, http):
        post = lambda path, **body: http.post(  # noqa: E731
            f"/api{path}", json=body, base_url=ORIGIN, headers=HEADERS
        )
        assert post("/db/check", quick="yes").status_code == 422
        assert post("/metrics/send", force="yes").status_code == 422
        assert post("/tiers/use").status_code == 422
        assert post("/tiers/use", tier="warp").status_code == 422
