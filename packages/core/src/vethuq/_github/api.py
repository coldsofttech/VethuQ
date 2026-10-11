"""A small client for the parts of the GitHub REST API runner setup needs."""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from vethuq._errors import _GitHubAuthError, _GitHubError, _GitHubSetupError

API = "https://api.github.com"
# (method, url, headers, body) -> (status, parsed JSON or None)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


def send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
    """The real transport: https to api.github.com only."""
    if not url.startswith(API + "/"):
        raise ValueError("only api.github.com is used")
    request = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, {"message": raw[:200].decode("utf-8", "replace")}


class _Api:
    """Calls GitHub as the owner of `token`. The token is only ever put in the request header."""

    OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
    REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

    def __init__(self, token: str, transport: Transport | None = None) -> None:
        if not isinstance(token, str) or not token.strip():
            raise _GitHubAuthError(
                "No GitHub token was given.",
                "Pass token=..., or set VETHUQ_GITHUB_TOKEN. Create a fine-grained token at "
                "github.com/settings/personal-access-tokens.",
            )
        self._token = token.strip()
        self._transport = transport or send

    def call(
        self, method: str, path: str, body: dict[str, Any] | None = None, ok: tuple[int, ...] = ()
    ) -> tuple[int, Any]:
        """One request. Statuses in `ok` (besides 2xx) are returned; anything else raises."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "vethuq",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            status, payload = self._transport(method, API + path, headers, data)
        except OSError as exc:
            raise _GitHubSetupError(
                f"Couldn't reach GitHub ({type(exc).__name__}).", "Check the connection."
            ) from None
        if 200 <= status < 300 or status in ok:
            return status, payload
        message = payload.get("message", "") if isinstance(payload, dict) else ""
        if status == 401:
            raise _GitHubAuthError(
                "GitHub rejected the token.", "Check it hasn't expired or been revoked."
            )
        if status == 403:
            raise _GitHubAuthError(
                f"The token isn't allowed to do that ({message or 'forbidden'}).",
                "It needs access to the runner repository: Contents, Actions, Secrets and "
                "Workflows (read and write), and Administration to create or delete it.",
            )
        if status == 429:
            raise _GitHubError("GitHub is rate limiting requests.", "Try again in a few minutes.")
        raise _GitHubSetupError(f"GitHub answered {status}: {message or 'no details'}.")

    # ----- what setup uses --------------------------------------------------------------------

    def user(self) -> str:
        """The login the token belongs to."""
        return self.call("GET", "/user")[1]["login"]

    def repo(self, owner: str, name: str) -> dict[str, Any] | None:
        status, payload = self.call("GET", f"/repos/{owner}/{name}", ok=(404,))
        return None if status == 404 else payload

    def create_repo(
        self, owner: str, name: str, *, private: bool, description: str, as_user: bool
    ) -> dict[str, Any]:
        path = "/user/repos" if as_user else f"/orgs/{owner}/repos"
        body = {
            "name": name,
            "private": private,
            "description": description,
            "auto_init": True,  # a first commit, so files can be added through the API
            "has_issues": False,
            "has_wiki": False,
            "has_projects": False,
        }
        return self.call("POST", path, body)[1]

    def delete_repo(self, owner: str, name: str) -> None:
        self.call("DELETE", f"/repos/{owner}/{name}")

    @staticmethod
    def _file(owner: str, name: str, path: str) -> str:
        return f"/repos/{owner}/{name}/contents/{quote(path)}"

    def read_file(self, owner: str, name: str, path: str) -> tuple[str, str] | None:
        """(text, sha) of a file, or None if it isn't there."""
        status, payload = self.call("GET", self._file(owner, name, path), ok=(404,))
        if status == 404 or not isinstance(payload, dict) or "content" not in payload:
            return None
        text = base64.b64decode(payload["content"]).decode("utf-8")
        return text, payload["sha"]

    def write_file(
        self, owner: str, name: str, path: str, text: str, message: str, branch: str,
        sha: str | None = None,
    ) -> None:  # fmt: skip
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        self.call("PUT", self._file(owner, name, path), body)

    def secret_key(self, owner: str, name: str) -> tuple[str, str]:
        """(key id, base64 public key) to encrypt a secret with."""
        payload = self.call("GET", f"/repos/{owner}/{name}/actions/secrets/public-key")[1]
        return payload["key_id"], payload["key"]

    def put_secret(self, owner: str, name: str, secret: str, encrypted: str, key_id: str) -> None:
        self.call(
            "PUT",
            f"/repos/{owner}/{name}/actions/secrets/{secret}",
            {"encrypted_value": encrypted, "key_id": key_id},
        )

    def has_secret(self, owner: str, name: str, secret: str) -> bool:
        status, _ = self.call("GET", f"/repos/{owner}/{name}/actions/secrets/{secret}", ok=(404,))
        return status != 404

    def read_only_workflows(self, owner: str, name: str) -> bool:
        """Make jobs in the repository start with read-only permissions. Best effort."""
        try:
            self.call(
                "PUT",
                f"/repos/{owner}/{name}/actions/permissions/workflow",
                {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
            )
        except (_GitHubAuthError, _GitHubSetupError):
            return False
        return True
