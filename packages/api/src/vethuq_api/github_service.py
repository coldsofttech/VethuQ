"""The GitHub tier for the interface: the runner repository and the jobs sent to it.

The add-on is optional, so it is imported only when asked. A GitHub token is used for the call and
is never stored by VethuQ; if the person asks, it is kept in this process's memory (and in its
`VETHUQ_GITHUB_TOKEN` variable, which index runs read) until the application closes.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

ADDON_ID = "github"
TOKEN_VARIABLES = ("VETHUQ_GITHUB_TOKEN", "GITHUB_TOKEN")


def _default_factory(client: Any) -> Any:
    from vethuq.addons.github import GitHub  # noqa: PLC0415 - an optional add-on

    return GitHub(client)


class GitHubService:
    def __init__(
        self, client: Callable[[], Any], factory: Callable[[Any], Any] = _default_factory
    ) -> None:
        self._client = client
        self._factory = factory
        self._lock = threading.Lock()
        self._session_token: str | None = None
        self._set_variable = False

    # ----- is it there ------------------------------------------------------------------------

    def availability(self) -> dict[str, object]:
        """Whether the add-on is installed and running, and not switched off by the policy."""
        client = self._client()
        info = client.addons.get(ADDON_ID)
        if info is None:
            return {
                "installed": False,
                "enabled": False,
                "reason": "The GitHub add-on is not installed.",
            }
        if info.status.value != "loaded":
            return {
                "installed": True,
                "enabled": False,
                "reason": info.detail or f"The GitHub add-on is {info.status.value}.",
            }
        rule = client.policy.current().policy.addons.get(ADDON_ID)
        if rule is not None and not rule.enabled:
            return {
                "installed": True,
                "enabled": False,
                "reason": rule.message or "The GitHub add-on has been switched off.",
            }
        return {"installed": True, "enabled": True, "reason": ""}

    # ----- the token --------------------------------------------------------------------------

    def _addon(self) -> Any | None:
        """The add-on's GitHub class, or None when it is not there to ask."""
        try:
            return self._github() if self.availability()["enabled"] else None
        except Exception:  # noqa: BLE001 - the token bar must still draw
            return None

    def token_state(self) -> dict[str, object]:
        """Where a token is: the environment, this session's memory, the credential store."""
        github = self._addon()
        source = github.token_source() if github and hasattr(github, "token_source") else None
        store = getattr(github, "credential_store_available", lambda: False)() if github else False
        with self._lock:
            return {
                "environment": any(os.environ.get(v) for v in TOKEN_VARIABLES),
                "session": self._session_token is not None,
                "stored": source == "credential-manager",
                "store_available": bool(store),
            }

    def store_token(self, token: str) -> dict[str, object]:
        """Save the token in the operating system's credential store (Credential Manager)."""
        github = self._github()
        if not hasattr(github, "remember_token"):
            raise ValueError("This version of the GitHub add-on cannot save a token. Update it.")
        github.remember_token(token)
        return self.token_state()

    def forget_token(self) -> dict[str, object]:
        """Forget the session's token and the saved one (a token in the environment stays)."""
        self.remember_token(None)
        github = self._addon()
        if github is not None and hasattr(github, "forget_token"):
            github.forget_token()
        return self.token_state()

    def remember_token(self, token: str | None) -> dict[str, object]:
        """Keep a token for this session (None forgets it). It is never written to disk."""
        with self._lock:
            if token:
                self._session_token = token
                os.environ[TOKEN_VARIABLES[0]] = token
                self._set_variable = True
            else:
                self._session_token = None
                if self._set_variable:
                    os.environ.pop(TOKEN_VARIABLES[0], None)
                    self._set_variable = False
        return self.token_state()

    def _token(self, given: str | None) -> str | None:
        with self._lock:
            return given or self._session_token

    # ----- the runner -------------------------------------------------------------------------

    def _github(self) -> Any:
        return self._factory(self._client())

    def overview(self) -> dict[str, object]:
        """What can be shown without asking GitHub: the runner that was set up and its versions."""
        state = self.availability()
        data: dict[str, object] = {
            **state,
            "token": self.token_state(),
            "runner": None,
            "versions": [],
        }
        if not state["enabled"]:
            return data
        github = self._github()
        runner = github.runner()
        data["runner"] = runner.to_dict() if runner else None
        data["versions"] = [v.to_dict() for v in github.versions()]
        tier = next((t for t in self._client().tiers.list() if t.id == ADDON_ID), None)
        data["tier"] = tier.to_dict() if tier else None
        return data

    def status(self, token: str | None) -> dict[str, object]:
        return self._github().status(self._token(token)).to_dict()

    def setup(
        self,
        *,
        repo: str,
        owner: str | None,
        private: bool,
        token: str | None,
        master_key: str | None,
        workflow_ref: str | None,
        create: bool,
        adopt: bool,
    ) -> dict[str, object]:
        runner = self._github().setup(
            repo or "vethuq-runner",
            owner=owner or None,
            private=private,
            token=self._token(token),
            master_key=master_key or None,
            workflow_ref=workflow_ref or None,
            create=create,
            adopt=adopt,
        )
        return runner.to_dict()

    def update(self, token: str | None, workflow_ref: str | None) -> dict[str, object]:
        return self._github().update(self._token(token), workflow_ref or None).to_dict()

    def remove(self, token: str | None, delete_repo: bool, delete_key: bool) -> dict[str, object]:
        runner = self._github().remove(
            self._token(token), delete_repo=delete_repo, delete_key=delete_key
        )
        return runner.to_dict()

    # ----- the jobs ---------------------------------------------------------------------------

    def jobs(self, limit: int) -> list[dict[str, object]]:
        """The jobs sent to GitHub, newest first."""
        jobs = self._client().index.jobs(limit=limit)
        return [j.to_dict() for j in jobs if j.tier == ADDON_ID]
