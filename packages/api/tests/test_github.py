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

    stored: str | None = None
    store_exists = True

    def token_source(self):
        return "credential-manager" if FakeGitHub.stored else None

    def credential_store_available(self):
        return FakeGitHub.store_exists

    def remember_token(self, token, *, verify=True):
        FakeGitHub.calls.append(("remember", token))
        if token == "bad":
            raise AddonError("The token was rejected.", "Make a new one.")
        FakeGitHub.stored = token

    def forget_token(self):
        had = FakeGitHub.stored is not None
        FakeGitHub.stored = None
        return had

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
    FakeGitHub.stored = None
    FakeGitHub.store_exists = True
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
        assert svc.token_state() == {
            "environment": False,
            "session": False,
            "stored": False,
            "store_available": True,
        }
        assert svc.remember_token("secret")["session"] is True
        assert os.environ[TOKEN_VARIABLES[0]] == "secret"
        svc.status(None)
        assert FakeGitHub.calls[-1] == ("status", "secret")  # used when none is given
        assert svc.remember_token(None)["session"] is False
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


class TestTheCredentialStore:
    def test_a_token_is_saved_in_the_store_and_reported_as_stored(self):
        svc = service()
        state = svc.store_token("ghp_good")
        assert state["stored"] is True and state["session"] is False
        assert FakeGitHub.calls[-1] == ("remember", "ghp_good")
        assert "ghp_good" not in os.environ.get(TOKEN_VARIABLES[0], "")

    def test_forgetting_clears_the_session_and_the_store_but_not_the_environment(self, monkeypatch):
        svc = service()
        svc.store_token("ghp_good")
        svc.remember_token("session-only")
        monkeypatch.setenv(TOKEN_VARIABLES[1], "mine")
        state = svc.forget_token()
        assert (state["stored"], state["session"]) == (False, False)
        assert os.environ[TOKEN_VARIABLES[1]] == "mine"

    def test_a_computer_with_no_store_says_so(self):
        FakeGitHub.store_exists = False
        assert service().token_state()["store_available"] is False

    def test_an_old_add_on_without_the_feature_is_told_to_update(self):
        old = GitHubService(
            lambda: client_with(LOADED), factory=lambda c: SimpleNamespace(runner=lambda: None)
        )
        with pytest.raises(ValueError, match="Update it"):
            old.store_token("x")


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
        assert post("token").status_code == 422  # nothing to keep
        assert post("token", token="x", store="yes").status_code == 422
        assert http.post("/api/github/token", json={}, base_url=ORIGIN).status_code == 403
