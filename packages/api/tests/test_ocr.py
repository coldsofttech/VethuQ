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
from vethuq_api.ocr_service import OcrService

HEADERS = {"Origin": ORIGIN}


class FakeModels:
    """Models whose downloading waits for the test, so the running job can be looked at."""

    cache_dir = "/models"

    def __init__(self, fail: bool = False) -> None:
        self.gate = threading.Event()
        self.fail = fail
        self.calls: list[tuple] = []

    def list(self, languages=None):
        return [
            SimpleNamespace(to_dict=lambda: {"name": "det", "installed": True, "size_bytes": 10}),
            SimpleNamespace(to_dict=lambda: {"name": "rec", "installed": False, "size_bytes": 0}),
        ]

    def download(self, languages, on_progress):
        self.calls.append(("download", languages))
        on_progress("rec", "downloading")
        self.gate.wait(5)
        if self.fail:
            raise RuntimeError("Couldn't download: rec.")
        on_progress("rec", "ready")

    def redownload(self, names, languages):
        self.calls.append(("redownload", names, languages))
        self.gate.wait(5)

    def clear(self, languages, include_shared=False):
        self.calls.append(("clear", languages, include_shared))
        return ["rec"]

    def clean(self):
        return ["old"]


@pytest.fixture
def models():
    return FakeModels()


@pytest.fixture
def service(models):
    client = SimpleNamespace(ocr=SimpleNamespace(models=models))
    return OcrService(lambda: client)


def wait_done(service):
    for _ in range(100):
        if not service.job()["running"]:
            return service.job()
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


class TestListing:
    def test_a_real_client_lists_engines_phases_and_models(self, tmp_path):
        with VethuQ(tmp_path / "v.db") as client:
            service = OcrService(lambda: client)
            assert {e["id"] for e in service.engines()} >= {"paddle"}
            orders = [p["order"] for p in service.phases()]
            assert orders == sorted(orders) and orders
            models = service.models()
            assert models["folder"].endswith("models") and models["items"]
            assert models["installed"] == 0 and models["size_bytes"] == 0

    def test_the_models_say_how_much_is_installed(self, service):
        listed = service.models(["en"])
        assert (listed["installed"], listed["size_bytes"], listed["folder"]) == (1, 10, "/models")


class TestDownloading:
    def test_a_download_runs_on_a_thread_and_reports_progress(self, service, models):
        first = service.start("download", ["en"])
        assert first["running"] and first["action"] == "download"
        time.sleep(0.05)
        assert service.job()["progress"] == {"rec": "downloading"}
        models.gate.set()
        done = wait_done(service)
        assert done["finished"] and done["error"] is None
        assert done["progress"] == {"rec": "ready"}
        assert models.calls == [("download", ["en"])]

    def test_only_one_job_runs_at_a_time(self, service, models):
        service.start("download")
        with pytest.raises(IndexingRefusedError) as refused:
            service.start("redownload")
        assert refused.value.status == 409
        with pytest.raises(IndexingRefusedError):
            service.clean()
        models.gate.set()
        wait_done(service)

    def test_a_failure_says_why(self, models):
        models.fail = True
        models.gate.set()
        service = OcrService(lambda: SimpleNamespace(ocr=SimpleNamespace(models=models)))
        service.start("download")
        done = wait_done(service)
        assert done["error"] == "Couldn't download: rec." and not done["running"]

    def test_redownload_takes_names_and_a_bad_action_is_refused(self, service, models):
        models.gate.set()
        service.start("redownload", ["en"], ["rec"])
        wait_done(service)
        assert models.calls == [("redownload", ["rec"], ["en"])]
        with pytest.raises(ValueError):
            service.start("explode")


class TestRemoving:
    def test_clear_needs_a_language_and_clean_removes_what_nothing_uses(self, service, models):
        assert service.clear(["en"], True) == ["rec"]
        assert models.calls == [("clear", ["en"], True)]
        with pytest.raises(ValueError):
            service.clear([], False)
        assert service.clean() == ["old"]


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
        overview = http.get("/api/ocr", base_url=ORIGIN).get_json()
        assert overview["engines"] and overview["phases"]
        models = http.get("/api/ocr/models?language=en", base_url=ORIGIN).get_json()
        assert models["items"] and "folder" in models
        assert http.get("/api/ocr/job", base_url=ORIGIN).get_json()["running"] is False
        cleaned = http.post("/api/ocr/models/clean", base_url=ORIGIN, headers=HEADERS)
        assert cleaned.get_json() == {"removed": []}

    def test_bad_requests_are_refused(self, http):
        post = lambda path, **body: http.post(  # noqa: E731
            f"/api/ocr/models/{path}", json=body, base_url=ORIGIN, headers=HEADERS
        )
        assert post("explode").status_code == 422
        assert post("clear").status_code == 422  # no language
        assert post("download", languages="en").status_code == 422
        assert http.post("/api/ocr/models/clean", base_url=ORIGIN).status_code == 403
