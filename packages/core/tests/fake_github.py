"""A stand-in for the parts of api.github.com that runner setup uses."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from nacl.public import PrivateKey, SealedBox


class FakeGitHub:
    def __init__(self, login: str = "octo", token: str = "ghp_good") -> None:  # noqa: S107
        self.login = login
        self.token = token
        self.orgs = {"acme"}
        self.repos: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.forbidden: list[str] = []  # path fragments that answer 403
        self.fail: dict[str, int] = {}  # path fragment -> status
        self.key = PrivateKey.generate()
        self.key_id = "kid-1"
        self.tokens_seen: set[str] = set()

    # ----- the transport -----------------------------------------------------------------------

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        path = url.removeprefix("https://api.github.com")
        self.calls.append((method, path))
        self.tokens_seen.add(headers.get("Authorization", ""))
        if headers.get("Authorization") != f"Bearer {self.token}":
            return 401, {"message": "Bad credentials"}
        for fragment, status in self.fail.items():
            if fragment in path:
                return status, {"message": "boom"}
        if any(fragment in path for fragment in self.forbidden):
            return 403, {"message": "Resource not accessible by personal access token"}
        data = json.loads(body) if body else None
        return self.route(method, path, data)

    def route(self, method: str, path: str, data: Any):
        if path == "/user":
            return 200, {"login": self.login}
        if path == "/user/repos" and method == "POST":
            return self.create(self.login, data)
        if (m := re.fullmatch(r"/orgs/([^/]+)/repos", path)) and method == "POST":
            if m[1] not in self.orgs:
                return 404, {"message": "Not Found"}
            return self.create(m[1], data)
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)(/.*)?", path)
        if not m:
            return 404, {"message": "Not Found"}
        owner, name, rest = m[1], m[2], m[3] or ""
        repo = self.repos.get(f"{owner}/{name}".lower())
        if repo is None:
            return 404, {"message": "Not Found"}
        if rest == "":
            if method == "DELETE":
                del self.repos[f"{owner}/{name}".lower()]
                return 204, None
            return 200, self.describe(owner, name, repo)
        if rest.startswith("/contents/"):
            return self.contents(method, rest.removeprefix("/contents/"), repo, data)
        if rest == "/actions/secrets/public-key":
            key = base64.b64encode(bytes(self.key.public_key)).decode()
            return 200, {"key_id": self.key_id, "key": key}
        if rest.startswith("/actions/secrets/"):
            secret = rest.removeprefix("/actions/secrets/")
            if method == "PUT":
                repo["secrets"][secret] = data
                return 201, None
            return (
                (200, {"name": secret}) if secret in repo["secrets"] else (404, {"message": "no"})
            )
        if rest == "/actions/permissions/workflow" and method == "PUT":
            repo["workflow_permissions"] = data["default_workflow_permissions"]
            return 204, None
        return 404, {"message": "Not Found"}

    def create(self, owner: str, data: dict[str, Any]):
        full = f"{owner}/{data['name']}".lower()
        if full in self.repos:
            return 422, {"message": "name already exists"}
        files = {}
        if data.get("auto_init"):
            files["README.md"] = ("# new\n", self.sha("# new\n"))
        self.repos[full] = {
            "owner": owner,
            "name": data["name"],
            "private": data["private"],
            "default_branch": "main",
            "description": data.get("description"),
            "files": files,
            "secrets": {},
        }
        return 201, self.describe(owner, data["name"], self.repos[full])

    @staticmethod
    def describe(owner: str, name: str, repo: dict[str, Any]) -> dict[str, Any]:
        return {
            "full_name": f"{owner}/{name}",
            "private": repo["private"],
            "default_branch": repo["default_branch"],
        }

    @staticmethod
    def sha(text: str) -> str:
        return hashlib.sha1(text.encode()).hexdigest()  # noqa: S324 - a stand-in for git's id

    def contents(self, method: str, path: str, repo: dict[str, Any], data: Any):
        files = repo["files"]
        if method == "GET":
            if path not in files:
                return 404, {"message": "Not Found"}
            text, sha = files[path]
            return 200, {"content": base64.b64encode(text.encode()).decode(), "sha": sha}
        if path in files and data.get("sha") != files[path][1]:
            return 422, {"message": "sha wasn't supplied"}
        text = base64.b64decode(data["content"]).decode()
        files[path] = (text, self.sha(text))
        repo.setdefault("commits", []).append(data["message"])
        return 200 if path in files else 201, {"content": {"path": path}}

    # ----- looking at the result ---------------------------------------------------------------

    def repo(self, full_name: str) -> dict[str, Any]:
        return self.repos[full_name.lower()]

    def secret_value(self, full_name: str, name: str) -> str:
        """What the secret decrypts to with the private key."""
        stored = self.repo(full_name)["secrets"][name]
        assert stored["key_id"] == self.key_id
        return SealedBox(self.key).decrypt(base64.b64decode(stored["encrypted_value"])).decode()

    def count(self, method: str, fragment: str) -> int:
        return sum(1 for m, p in self.calls if m == method and fragment in p)
