from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from api_support import ORIGIN

from vethuq import VethuQ
from vethuq_addon_api import AddonError
from vethuq_api import allow_host, create_app
from vethuq_api.core import VethuQCore
from vethuq_api.github_service import TOKEN_VARIABLES, GitHubService

HEADERS = {"Origin": ORIGIN}


class Runner:
    def __init__(self, repo="vethuq-runner", **extra):
        self.repo = repo
        self.extra = extra

    def to_dict(self):
        return {
            "owner": "me",
            "repo": self.repo,
            "private": True,
            "url": "https://github.com/me/" + self.repo,
            **self.extra,
        }


class FakeGitHub:
    """What the add-on's GitHub class does, recording how it was called."""

    set_up: Runner | None = None
    calls: list = []

    def __init__(self, client):
        self.client = client

    def runner(self):
        return FakeGitHub.set_up

    def versions(self):
        return [SimpleNamespace(to_dict=lambda: {"workflow_ref": "v1", "status": "current"})]

    def status(self, token=None):
        FakeGitHub.calls.append(("status", token))
        return SimpleNamespace(to_dict=lambda: {"ok": True, "problems": [], "repo_found": True})

    def setup(self, repo, **kwargs):
        FakeGitHub.calls.append(("setup", repo, kwargs))
        FakeGitHub.set_up = Runner(repo)
        return FakeGitHub.set_up

    def update(self, token=None, workflow_ref=None):
        FakeGitHub.calls.append(("update", token, workflow_ref))
        return Runner(workflow_ref=workflow_ref or "v2")

    def remove(self, token=None, *, delete_repo=False, delete_key=False):
        FakeGitHub.calls.append(("remove", token, delete_repo, delete_key))
        FakeGitHub.set_up = None
        return Runner()


def client_with(addon=None, rule=None, jobs=()):
    return SimpleNamespace(
        addons=SimpleNamespace(get=lambda _id: addon),
        policy=SimpleNamespace(
            current=lambda: SimpleNamespace(
                policy=SimpleNamespace(addons={"github": rule} if rule else {})
            )
        ),
        tiers=SimpleNamespace(
            list=lambda: [
                SimpleNamespace(id="github", to_dict=lambda: {"id": "github", "available": True})
            ]
        ),
        index=SimpleNamespace(jobs=lambda limit: list(jobs)),
    )


LOADED = SimpleNamespace(status=SimpleNamespace(value="loaded"), detail="")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    FakeGitHub.set_up = None
    FakeGitHub.calls = []
    for name in TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def service(client=None):
    return GitHubService(lambda: client or client_with(LOADED), factory=FakeGitHub)


class TestAvailability:
    def test_not_installed(self, tmp_path):
        with VethuQ(tmp_path / "v.db") as real:
            state = GitHubService(lambda: real).availability()
        assert (
            state["installed"] is False
            and state["enabled"] is False
            and "not installed" in state["reason"]
        )

    def test_installed_and_running(self):
        assert service().availability() == {"installed": True, "enabled": True, "reason": ""}

    def test_broken_or_switched_off(self):
        broken = SimpleNamespace(status=SimpleNamespace(value="failed"), detail="ImportError")
        assert service(client_with(broken)).availability()["reason"] == "ImportError"
        off = SimpleNamespace(enabled=False, message="Withdrawn.")
        assert service(client_with(LOADED, off)).availability() == {
            "installed": True,
            "enabled": False,
            "reason": "Withdrawn.",
        }


class TestRunner:
    def test_nothing_set_up_yet(self):
        data = service().overview()
        assert (
            data["enabled"]
            and data["runner"] is None
            and data["versions"][0]["workflow_ref"] == "v1"
        )
        assert data["tier"]["id"] == "github"

    def test_setup_passes_what_was_asked_and_the_runner_shows_after(self):
        svc = service()
        runner = svc.setup(
            repo="my-runner",
            owner=None,
            private=True,
            token="t",
            master_key=None,
            workflow_ref=None,
            create=True,
            adopt=False,
        )
        assert runner["repo"] == "my-runner"
        (_, repo, kwargs) = FakeGitHub.calls[0]
        assert repo == "my-runner" and kwargs["token"] == "t" and kwargs["private"] is True
        assert svc.overview()["runner"]["repo"] == "my-runner"

    def test_status_update_and_remove_use_the_given_token(self):
        svc = service()
        svc.status("abc")
        svc.update("abc", "v2")
        svc.remove("abc", True, False)
        assert FakeGitHub.calls == [
            ("status", "abc"),
            ("update", "abc", "v2"),
            ("remove", "abc", True, False),
        ]


class TestToken:
    def test_a_remembered_token_is_kept_in_memory_and_the_variable_only(self):
        svc = service()
        assert svc.token_state() == {"environment": False, "session": False}
        assert svc.remember_token("secret") == {"environment": True, "session": True}
        assert os.environ[TOKEN_VARIABLES[0]] == "secret"
        svc.status(None)
        assert FakeGitHub.calls[-1] == ("status", "secret")  # used when none is given
        assert svc.remember_token(None) == {"environment": False, "session": False}
        assert TOKEN_VARIABLES[0] not in os.environ

    def test_a_token_from_the_environment_is_left_alone_when_forgetting(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VARIABLES[0], "mine")
        svc = service()
        svc.remember_token(None)
        assert os.environ[TOKEN_VARIABLES[0]] == "mine"

    def test_a_given_token_beats_the_remembered_one(self):
        svc = service()
        svc.remember_token("kept")
        svc.status("given")
        assert FakeGitHub.calls[-1] == ("status", "given")
        svc.remember_token(None)


class TestJobs:
    def test_only_the_jobs_sent_to_github(self):
        jobs = [
            SimpleNamespace(tier="github", to_dict=lambda: {"id": 1, "tier": "github"}),
            SimpleNamespace(tier="local", to_dict=lambda: {"id": 2, "tier": "local"}),
        ]
        assert service(client_with(LOADED, jobs=jobs)).jobs(50) == [{"id": 1, "tier": "github"}]


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

    def test_without_the_add_on_it_says_so(self, http):
        data = http.get("/api/github", base_url=ORIGIN).get_json()
        assert data["installed"] is False and data["runner"] is None
        assert http.get("/api/github/availability", base_url=ORIGIN).get_json()["enabled"] is False
        assert http.get("/api/github/jobs", base_url=ORIGIN).get_json() == {"jobs": []}

    def test_errors_from_the_add_on_become_readable_answers(self, http, monkeypatch):
        class Failing(AddonError):
            pass

        Failing.__name__ = "GitHubAuthError"

        def boom(self, token):
            raise Failing("The token was rejected.", "Make a new one.")

        monkeypatch.setattr(GitHubService, "status", boom)
        response = http.post("/api/github/status", json={}, base_url=ORIGIN, headers=HEADERS)
        assert response.status_code == 401
        assert response.get_json() == {
            "error": "The token was rejected. Make a new one.",
            "kind": "GitHubAuthError",
        }

    def test_bad_values_are_refused(self, http):
        post = lambda path, **body: http.post(  # noqa: E731
            f"/api/github/{path}", json=body, base_url=ORIGIN, headers=HEADERS
        )
        assert post("setup", private="yes").status_code == 422
        assert post("remove", delete_repo="yes").status_code == 422
        assert post("token", token=5).status_code == 422
        assert http.post("/api/github/token", json={}, base_url=ORIGIN).status_code == 403
