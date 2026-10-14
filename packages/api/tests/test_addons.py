from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_api import allow_host, create_app
from vethuq_api.addons_service import AddonsService
from vethuq_api.core import VethuQCore
from vethuq_api.indexing import IndexingRefusedError

HEADERS = {"Origin": ORIGIN}


class Pip:
    """A pip that records what it was asked and waits to be let go."""

    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, args):
        self.calls.append(args)
        return self.code, ["Collecting x", "Done"] if self.code == 0 else ["ERROR: no match"]


@pytest.fixture
def vethuq(tmp_path):
    instance = VethuQ(tmp_path / "vethuq.db")
    yield instance
    instance.close()


def with_policy(vethuq, **addons):
    """The real client, with a policy that says `addons` (id -> AddonPolicy-like)."""
    rules = {k: SimpleNamespace(**v) for k, v in addons.items()}
    return SimpleNamespace(
        addons=vethuq.addons,
        policy=SimpleNamespace(
            current=lambda: SimpleNamespace(policy=SimpleNamespace(addons=rules))
        ),
        close=vethuq.close,
    )


def wait(service):
    for _ in range(200):
        if not service.job()["running"]:
            return service.job()
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


class TestInstalled:
    def test_each_add_on_says_its_state(self, vethuq):
        service = AddonsService(lambda: vethuq)
        rows = {r["id"]: r for r in service.installed()}
        assert rows["pdf"]["status"] == "loaded" and rows["pdf"]["version"]
        assert rows["pdf"]["disabled"] is False and rows["pdf"]["restart"] is False
        assert rows["pdf"]["update"] is False and rows["pdf"]["licence"] is False

    def test_an_announced_newer_version_offers_an_update_and_a_kill_switch_shows(self, vethuq):
        client = with_policy(
            vethuq,
            pdf={"enabled": True, "latest": "99.0.0", "message": "Please update."},
            csv={"enabled": False, "latest": None, "message": "Withdrawn."},
        )
        rows = {r["id"]: r for r in AddonsService(lambda: client).installed()}
        assert rows["pdf"]["update"] and rows["pdf"]["latest"] == "99.0.0"
        assert rows["pdf"]["message"] == "Please update."
        assert rows["csv"]["switched_off"] is True and rows["csv"]["update"] is False

    def test_an_older_or_same_version_offers_nothing(self, vethuq):
        version = {r["id"]: r["version"] for r in AddonsService(lambda: vethuq).installed()}["pdf"]
        client = with_policy(vethuq, pdf={"enabled": True, "latest": version, "message": None})
        assert not AddonsService(lambda: client).installed()[0]["update"]

    def test_turning_one_off_waits_for_a_restart(self, vethuq):
        service = AddonsService(lambda: vethuq)
        assert service.set_enabled("csv", False)["disabled"] is True
        row = next(r for r in service.installed() if r["id"] == "csv")
        assert row["disabled"] and row["status"] == "loaded" and row["restart"] is True
        service.set_enabled("csv", True)
        assert next(r for r in service.installed() if r["id"] == "csv")["restart"] is False
        with pytest.raises(ValueError):
            service.set_enabled("english", False)


class TestPacks:
    def test_the_packs_vethuq_names_are_listed_with_what_is_installed(self, vethuq):
        packs = {p["id"]: p for p in AddonsService(lambda: vethuq).packs()}
        assert {"images", "deep-scan", "search", "web", "data"} <= set(packs)
        assert packs["data"]["note"]
        assert packs["images"]["packages"][0]["name"] == "vethuq-bundle-image"
        assert packs["images"]["note"]
        assert isinstance(packs["fuzzy"]["installed"], bool)


class TestInstalling:
    def test_a_pack_is_installed_by_its_names_and_the_add_ons_are_looked_for_again(self, vethuq):
        pip = Pip()
        service = AddonsService(lambda: vethuq, runner=pip)
        started = service.install("images")
        assert started["running"] and started["action"] == "install"
        done = wait(service)
        assert done["error"] is None and done["log"] == ["Collecting x", "Done"]
        (args,) = pip.calls
        assert args[0] == "install" and "--no-input" in args
        assert args[-1].startswith("vethuq-bundle-image") and ";" not in args[-1]

    def test_only_packs_vethuq_names_can_be_asked_for(self, vethuq):
        pip = Pip()
        service = AddonsService(lambda: vethuq, runner=pip)
        for bad in ("evil", "images; rm -rf /", "../x", ""):
            with pytest.raises(ValueError):
                service.install(bad)
        assert pip.calls == []

    def test_an_update_upgrades_just_that_add_on(self, vethuq):
        client = with_policy(vethuq, pdf={"enabled": True, "latest": "99.0.0", "message": None})
        pip = Pip()
        service = AddonsService(lambda: client, runner=pip)
        service.update("pdf")
        wait(service)
        assert pip.calls == [
            [
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--upgrade",
                "vethuq-addon-pdf",
            ]
        ]
        with pytest.raises(ValueError):
            service.update("csv")  # no update announced

    def test_a_pip_failure_says_so_and_keeps_its_output(self, vethuq):
        service = AddonsService(lambda: vethuq, runner=Pip(code=1))
        service.install("images")
        done = wait(service)
        assert "pip could not finish" in done["error"] and done["log"] == ["ERROR: no match"]

    def test_one_job_at_a_time(self, vethuq):
        gate = []

        def slow(args):
            while not gate:
                time.sleep(0.01)
            return 0, []

        service = AddonsService(lambda: vethuq, runner=slow)
        service.install("images")
        with pytest.raises(IndexingRefusedError) as refused:
            service.install("web")
        assert refused.value.status == 409
        gate.append(1)
        wait(service)

    def test_a_packaged_copy_cannot_install(self, vethuq):
        service = AddonsService(lambda: vethuq, runner=Pip(), frozen=True)
        assert service.can_install()["ok"] is False
        with pytest.raises(IndexingRefusedError, match="packaged"):
            service.install("images")


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
        data = http.get("/api/addons", base_url=ORIGIN).get_json()
        assert data["installed"] and data["packs"] and data["install"]["ok"] in (True, False)
        assert http.get("/api/addons/job", base_url=ORIGIN).get_json()["running"] is False
        off = http.post(
            "/api/addons/csv/enabled", json={"enabled": False}, base_url=ORIGIN, headers=HEADERS
        )
        assert off.get_json()["disabled"] is True

    def test_bad_requests_are_refused(self, http):
        post = lambda path, **body: http.post(  # noqa: E731
            f"/api/addons/{path}", json=body, base_url=ORIGIN, headers=HEADERS
        )
        assert post("csv/enabled", enabled="no").status_code == 422
        assert post("nothing/enabled", enabled=False).status_code == 422
        assert post("packs/evil/install").status_code == 422
        assert post("csv/update").status_code == 422
        assert http.post("/api/addons/csv/enabled", json={}, base_url=ORIGIN).status_code == 403
