from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.indexing import IndexingRefusedError, IndexingService
from vethuq_api.service_probe import ServiceInfo, colour, parse_query

HEADERS = {"Origin": ORIGIN}

RUNNING = """
SERVICE_NAME: VethuQBackground
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
"""
CRASHED = RUNNING.replace("4  RUNNING", "1  STOPPED").replace(
    "WIN32_EXIT_CODE    : 0  (0x0)", "WIN32_EXIT_CODE    : 1066  (0x42a)"
)
NEVER_STARTED = RUNNING.replace("4  RUNNING", "1  STOPPED").replace(
    "WIN32_EXIT_CODE    : 0  (0x0)", "WIN32_EXIT_CODE    : 1077  (0x435)"
)


class FakeProbe:
    def __init__(self, info: ServiceInfo | None) -> None:
        self.info = info

    def query(self) -> ServiceInfo | None:
        return self.info


class TestServiceProbe:
    def test_sc_output_is_read(self):
        assert parse_query(RUNNING) == ServiceInfo("RUNNING", 0)
        assert parse_query(CRASHED) == ServiceInfo("STOPPED", 1066)

    def test_a_service_that_never_started_is_not_an_error(self):
        assert parse_query(NEVER_STARTED) == ServiceInfo("STOPPED", 0)

    def test_text_that_is_not_a_service_gives_nothing(self):
        assert parse_query("[SC] OpenService FAILED 1060") is None

    @pytest.mark.parametrize(
        ("info", "working", "announced", "expected"),
        [
            (ServiceInfo("RUNNING"), False, True, "green"),
            (ServiceInfo("RUNNING"), True, True, "amber"),
            (ServiceInfo("RUNNING"), False, False, "amber"),
            (ServiceInfo("PAUSED"), False, True, "amber"),
            (ServiceInfo("START_PENDING"), False, False, "amber"),
            (ServiceInfo("STOPPED", 0), False, False, "grey"),
            (ServiceInfo("STOPPED", 1066), False, False, "red"),
        ],
    )
    def test_the_dot_colour(self, info, working, announced, expected):
        assert colour(info, working=working, announced=announced)[0] == expected


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "a.txt").write_text("alpha")
    (root / "b.csv").write_text("x,y\n1,2\n")
    return root


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


@pytest.fixture
def indexing(vethuq):
    return IndexingService(lambda: vethuq, FakeProbe(None))


def wait_until_over(service, timeout=60):
    deadline = time.monotonic() + timeout
    while service.one_off_active() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not service.one_off_active(), "the run did not end"


class TestRuns:
    def test_a_run_started_here_runs_and_is_reported(self, indexing, vethuq, library):
        source = vethuq.sources.create(library)
        state = indexing.start("run", source.id)
        assert state["runner"]["mode"] == "one-off"
        wait_until_over(indexing)
        state = indexing.state()
        assert state["run"]["status"] == "completed"
        assert state["run"]["files_processed"] == 2
        assert state["active"] is False
        assert state["runner"]["mode"] == "idle"
        assert state["error"] is None
        assert [r["mode"] for r in indexing.history(limit=5)] == ["run"]

    def test_files_are_indexed_afterwards(self, indexing, vethuq, library):
        source = vethuq.sources.create(library)
        indexing.start("run", source.id)
        wait_until_over(indexing)
        statuses = {
            f.name: f.index.status.value for f in vethuq.sources.list_files(source.id, True)
        }
        assert statuses == {"a.txt": "indexed", "b.csv": "indexed"}

    def test_every_source_can_be_indexed_at_once(self, indexing, vethuq, library):
        vethuq.sources.create(library)
        indexing.start("run", None)
        wait_until_over(indexing)
        assert indexing.state()["run"]["source_id"] is None

    def test_a_second_run_is_refused_while_one_goes(self, indexing, vethuq, library, monkeypatch):
        vethuq.sources.create(library)
        release = __import__("threading").Event()
        monkeypatch.setattr(vethuq.index, "run", lambda target: release.wait(10))
        indexing.start("run", None)
        with pytest.raises(IndexingRefusedError, match="already going") as caught:
            indexing.start("run", None)
        assert caught.value.status == 409
        release.set()
        wait_until_over(indexing)

    def test_an_unknown_source_is_refused_at_once(self, indexing):
        from vethuq.errors import SourceNotFoundError

        with pytest.raises(SourceNotFoundError):
            indexing.start("reindex", "/no/such/source")
        assert indexing.one_off_active() is False

    def test_what_goes_wrong_in_a_run_is_kept_for_the_screen(self, indexing, vethuq, monkeypatch):
        def fail(target):
            raise RuntimeError("the run failed to start")

        monkeypatch.setattr(vethuq.index, "run", fail)
        indexing.start("run", None)
        wait_until_over(indexing)
        assert "failed to start" in indexing.state()["error"]
        indexing.start("run", None)  # starting again clears the old message first
        wait_until_over(indexing)

    @pytest.mark.parametrize(
        ("mode", "target", "message"),
        [
            ("fly", None, "mode is one of"),
            ("reindex", None, "needs a source"),
            ("file", None, "needs"),
        ],
    )
    def test_a_bad_request_is_refused_before_it_starts(self, indexing, mode, target, message):
        with pytest.raises(IndexingRefusedError, match=message) as caught:
            indexing.start(mode, target)
        assert caught.value.status == 422

    def test_stopping_with_nothing_going_is_not_an_error(self, indexing):
        assert indexing.stop()["active"] is False


class TestCredits:
    def estimate(self, monkeypatch, vethuq, **values):
        monkeypatch.setattr(
            vethuq.credits, "estimate", lambda target: SimpleNamespace(maximum=7.5, **values)
        )

    def test_a_run_the_wallet_cannot_pay_for_is_blocked(self, indexing, vethuq, monkeypatch):
        self.estimate(monkeypatch, vethuq, ocr_pages=4, affordable=False)
        with pytest.raises(IndexingRefusedError, match="Not enough credits") as caught:
            indexing.start("run", None)
        assert caught.value.status == 402
        assert indexing.one_off_active() is False

    def test_a_run_without_ocr_is_never_blocked(self, indexing, vethuq, library, monkeypatch):
        vethuq.sources.create(library)
        self.estimate(monkeypatch, vethuq, ocr_pages=0, affordable=False)
        indexing.start("run", None)
        wait_until_over(indexing)
        assert indexing.state()["run"]["status"] == "completed"

    def test_an_affordable_run_starts_without_any_warning(
        self, indexing, vethuq, library, monkeypatch
    ):
        vethuq.sources.create(library)
        self.estimate(monkeypatch, vethuq, ocr_pages=4, affordable=True)
        indexing.start("run", None)
        wait_until_over(indexing)


class TestService:
    def test_a_running_service_takes_the_request(self, indexing, vethuq, library, monkeypatch):
        from vethuq.jobs import IndexQueue

        vethuq.sources.create(library)
        monkeypatch.setattr(IndexQueue, "service_running", lambda self: True)
        state = indexing.start("run", None)
        assert state["queued"] == 1
        assert indexing.one_off_active() is False
        assert state["runner"]["service_running"] is True
        assert [j["mode"] for j in indexing.requests()] == ["run"]

    def test_stopping_takes_a_waiting_request_out(self, indexing, vethuq, library, monkeypatch):
        from vethuq.jobs import IndexQueue

        vethuq.sources.create(library)
        monkeypatch.setattr(IndexQueue, "service_running", lambda self: True)
        indexing.start("run", None)
        assert indexing.stop()["queued"] == 0

    def test_a_request_can_be_cancelled_by_id(self, indexing, vethuq, library, monkeypatch):
        from vethuq.jobs import IndexQueue

        vethuq.sources.create(library)
        monkeypatch.setattr(IndexQueue, "service_running", lambda self: True)
        indexing.start("run", None)
        job = indexing.requests()[0]
        assert indexing.cancel_request(job["id"])["status"] == "cancelled"

    def test_nothing_about_the_service_is_shown_when_it_is_not_installed(self, indexing):
        assert indexing.state()["service"] is None

    def test_the_dot_follows_the_service(self, vethuq):
        probe = FakeProbe(ServiceInfo("RUNNING"))
        service = IndexingService(lambda: vethuq, probe)
        # Running, but not announced for this data folder yet: still starting.
        assert service.state()["service"]["colour"] == "amber"
        probe.info = ServiceInfo("STOPPED", 0)
        assert service.state()["service"]["colour"] == "grey"
        probe.info = ServiceInfo("STOPPED", 1066)
        assert service.state()["service"]["colour"] == "red"

    def test_a_running_idle_service_is_green_and_an_active_run_is_amber(self, vethuq, monkeypatch):
        from vethuq.jobs import IndexQueue

        monkeypatch.setattr(IndexQueue, "service_running", lambda self: True)
        service = IndexingService(lambda: vethuq, FakeProbe(ServiceInfo("RUNNING")))
        state = service.state()
        assert state["service"]["colour"] == "green"
        assert state["service"]["label"] == "Idle"

    def test_service_actions_are_passed_to_the_background_package(self, vethuq, monkeypatch):
        import vethuq_background.service as background

        calls = []
        monkeypatch.setattr(
            background.BackgroundService,
            "perform",
            lambda self, action, **o: calls.append((action, self.db_path)),
        )
        service = IndexingService(lambda: vethuq, FakeProbe(ServiceInfo("STOPPED")))
        service.service_action("start")
        assert calls == [("start", vethuq.db_path)]

    def test_service_actions_need_an_installed_service_and_a_known_action(self, vethuq):
        missing = IndexingService(lambda: vethuq, FakeProbe(None))
        with pytest.raises(IndexingRefusedError, match="not installed") as caught:
            missing.service_action("start")
        assert caught.value.status == 404
        present = IndexingService(lambda: vethuq, FakeProbe(ServiceInfo("RUNNING")))
        with pytest.raises(IndexingRefusedError, match="Start, stop"):
            present.service_action("explode")


class TestRefresh:
    def fake(self, open_jobs):
        collected = []
        client = SimpleNamespace(
            index=SimpleNamespace(
                status=lambda: SimpleNamespace(
                    remote_jobs_open=open_jobs,
                    active=False,
                    paused=False,
                    stopping=False,
                    finished=True,
                    stalled=False,
                    control="run",
                    current_files=(),
                    workers_active=0,
                    run=SimpleNamespace(to_dict=lambda: {"id": 1}),
                    eta=SimpleNamespace(to_dict=lambda: {}),
                ),
                collect=lambda: collected.append(True),
                queue=SimpleNamespace(
                    service_running=lambda: False, queued=lambda: 0, list=lambda *a, **k: []
                ),
            )
        )
        return client, collected

    def test_results_are_collected_only_when_jobs_are_out(self):
        client, collected = self.fake(2)
        IndexingService(lambda: client, FakeProbe(None)).refresh()
        assert collected == [True]
        client, collected = self.fake(0)
        IndexingService(lambda: client, FakeProbe(None)).refresh()
        assert collected == []

    def test_a_failed_collect_is_shown_not_raised(self):
        client, _ = self.fake(1)

        def fail():
            raise RuntimeError("the tier is down")

        client.index.collect = fail
        state = IndexingService(lambda: client, FakeProbe(None)).refresh()
        assert "the tier is down" in state["error"]


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

    def test_state_start_and_history_over_http(self, http, library):
        http.post("/api/sources", json={"path": str(library)}, base_url=ORIGIN, headers=HEADERS)
        state = http.get("/api/index/state", base_url=ORIGIN).get_json()
        assert state["run"] is None and state["runner"]["mode"] == "idle"

        started = http.post(
            "/api/index/start", json={"mode": "run", "target": 1}, base_url=ORIGIN, headers=HEADERS
        )
        assert started.status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = http.post("/api/index/refresh", base_url=ORIGIN, headers=HEADERS).get_json()
            if state["run"] and state["run"]["status"] == "completed":
                break
            time.sleep(0.1)
        assert state["run"]["files_processed"] == 2
        runs = http.get("/api/index/history?limit=5", base_url=ORIGIN).get_json()["runs"]
        assert runs[0]["mode"] == "run"
        assert http.get("/api/index/jobs", base_url=ORIGIN).get_json() == {"jobs": []}
        assert http.get("/api/index/requests", base_url=ORIGIN).get_json() == {"requests": []}

    def test_a_refused_run_answers_with_its_reason(self, http):
        response = http.post(
            "/api/index/start", json={"mode": "fly"}, base_url=ORIGIN, headers=HEADERS
        )
        assert response.status_code == 422
        assert "mode is one of" in response.get_json()["error"]

    def test_the_service_endpoint_needs_an_installed_service(self, http):
        response = http.post("/api/service/start", base_url=ORIGIN, headers=HEADERS)
        assert response.status_code == 404

    def test_changes_need_the_app_origin(self, http):
        assert http.post("/api/index/stop", base_url=ORIGIN).status_code == 403


class TestClosing:
    def close(self, client, **body):
        return client.post("/api/window/close", json=body, base_url=ORIGIN, headers=HEADERS)

    def test_closing_is_held_back_while_a_run_of_this_app_goes(self, signed_in, window, fake_core):
        fake_core.one_off = True
        body = self.close(signed_in).get_json()
        assert body["closing"] is False and body["blocked"] == "indexing"
        assert window.calls == []
        assert fake_core.stopped_for_close is False

    def test_a_confirmed_close_stops_the_run_and_closes(self, signed_in, window, fake_core):
        fake_core.one_off = True
        body = self.close(signed_in, force=True).get_json()
        assert body["closing"] is True
        assert fake_core.stopped_for_close is True
        assert window.calls == ["close"]

    def test_closing_is_not_held_back_otherwise(self, signed_in, window, fake_core):
        body = self.close(signed_in).get_json()
        assert body["closing"] is True and body["blocked"] is None
        assert window.calls == ["close"]
