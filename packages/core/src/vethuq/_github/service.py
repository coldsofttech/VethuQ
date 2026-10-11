"""Setting up, checking, updating and removing the runner repository."""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from nacl.public import PublicKey, SealedBox

from vethuq._db import _Database
from vethuq._errors import (
    _GitHubNotSetUpError,
    _GitHubSetupError,
    _GitHubUnavailableError,
)
from vethuq._github.api import Transport, _Api
from vethuq._github.keys import _MasterKey
from vethuq._github.template import (
    README_PATH,
    SECRET_NAME,
    WORKFLOW_PATH,
    _Caller,
    _Compatibility,
    _Row,
)
from vethuq._paths import _Paths
from vethuq._settings import _Settings

_logger = logging.getLogger("vethuq.github")


@dataclass(frozen=True)
class _Config:
    """What is remembered about the runner (never the token, never the key)."""

    owner: str
    repo: str
    private: bool
    workflow_ref: str
    image: str
    protocol: int
    key_fingerprint: str
    set_up_at: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class _Check:
    repo_found: bool
    private: bool | None
    caller_ok: bool
    pinned_ref: str | None
    pinned_image: str | None
    secret_set: bool
    problems: list[str]


class _Runner:
    CONFIG_KEY = "github_runner"
    TOKEN_ENV = ("VETHUQ_GITHUB_TOKEN", "GITHUB_TOKEN")
    DESCRIPTION = "VethuQ runner: OCR in your own GitHub account (set up by VethuQ)"

    def __init__(
        self,
        database: _Database,
        feature: Callable[[], tuple[bool, str | None]],
        client_version: str,
        transport: Transport | None = None,
    ) -> None:
        self.database = database
        self.feature = feature
        self.client_version = client_version
        self.transport = transport

    # ----- plumbing ---------------------------------------------------------------------------

    def keys(self) -> _MasterKey:
        return _MasterKey(_Paths.github_dir(self.database.db_path, create=False))

    def gate(self) -> None:
        allowed, message = self.feature()
        if not allowed:
            raise _GitHubUnavailableError(
                message or "The GitHub tier isn't available right now.",
                "Try again later, or update VethuQ.",
            )

    def api(self, token: str | None) -> _Api:
        found = token or next((os.environ[n] for n in self.TOKEN_ENV if os.environ.get(n)), None)
        return _Api(found or "", self.transport)

    def config(self) -> _Config | None:
        with self.database.session() as session:
            raw = _Settings.get(session, self.CONFIG_KEY)
        if not raw:
            return None
        try:
            return _Config(**json.loads(raw))
        except (ValueError, TypeError):
            _logger.warning("The saved GitHub runner settings are unreadable")
            return None

    def save(self, config: _Config) -> None:
        with self.database.session() as session:
            _Settings.set(session, self.CONFIG_KEY, json.dumps(asdict(config)))

    def forget(self) -> None:
        with self.database.session() as session:
            _Settings.reset(session, self.CONFIG_KEY)

    def require(self) -> _Config:
        config = self.config()
        if config is None:
            raise _GitHubNotSetUpError(
                "No GitHub runner has been set up.", "Run client.github.setup(...) first."
            )
        return config

    # ----- the pieces -------------------------------------------------------------------------

    @staticmethod
    def seal(public_key_b64: str, secret: str) -> str:
        """Encrypt `secret` the way GitHub expects (a libsodium sealed box)."""
        box = SealedBox(PublicKey(base64.b64decode(public_key_b64)))
        return base64.b64encode(box.encrypt(secret.encode("utf-8"))).decode("ascii")

    def put_secret(self, api: _Api, owner: str, repo: str, key: str) -> None:
        key_id, public = api.secret_key(owner, repo)
        api.put_secret(owner, repo, SECRET_NAME, self.seal(public, key), key_id)

    def put_caller(self, api: _Api, owner: str, repo: str, branch: str, row: _Row) -> None:
        current = api.read_file(owner, repo, WORKFLOW_PATH)
        text = _Caller.render(row)
        if current is not None and current[0] == text:
            return
        message = f"VethuQ: set the runner to {row.workflow_ref}"
        api.write_file(
            owner, repo, WORKFLOW_PATH, text, message, branch, current[1] if current else None
        )

    # ----- setup ------------------------------------------------------------------------------

    def setup(
        self,
        repo: str,
        *,
        owner: str | None,
        private: bool,
        token: str | None,
        master_key: str | bytes | None,
        workflow_ref: str | None,
        create: bool,
        adopt: bool,
    ) -> _Config:
        self.gate()
        if not _Api.REPO_RE.match(repo or "") or repo in (".", ".."):
            raise _GitHubSetupError(f"{repo!r} isn't a valid repository name.")
        if owner is not None and not _Api.OWNER_RE.match(owner):
            raise _GitHubSetupError(f"{owner!r} isn't a valid GitHub user or organization.")
        row = _Compatibility.choose(self.client_version, workflow_ref)
        api = self.api(token)
        login = api.user()
        target = owner or login
        found = api.repo(target, repo)
        created = False
        if found is None:
            if not create:
                raise _GitHubSetupError(f"{target}/{repo} doesn't exist.", "Allow create=True.")
            found = api.create_repo(
                target, repo, private=private, description=self.DESCRIPTION,
                as_user=target.lower() == login.lower(),
            )  # fmt: skip
            created = True
        elif not adopt and self.config() is None and not self._ours(api, target, repo):
            raise _GitHubSetupError(
                f"{target}/{repo} already exists and wasn't set up by VethuQ.",
                "Choose another name, or pass adopt=True to add the runner to it.",
            )
        visibility_private = bool(found.get("private", True))
        if not private and visibility_private and not created:
            _logger.info("%s/%s is private; leaving it private", target, repo)
        branch = found.get("default_branch") or "main"
        key = self.keys().obtain(master_key)
        self.put_caller(api, target, repo, branch, row)
        if created:
            readme = api.read_file(target, repo, README_PATH)
            api.write_file(
                target, repo, README_PATH, _Caller.template("README.md"),
                "VethuQ: describe this repository", branch, readme[1] if readme else None,
            )  # fmt: skip
        self.put_secret(api, target, repo, key)
        api.read_only_workflows(target, repo)
        config = _Config(
            owner=target,
            repo=repo,
            private=visibility_private,
            workflow_ref=row.workflow_ref,
            image=row.image,
            protocol=row.protocol,
            key_fingerprint=_MasterKey.fingerprint(key),
            set_up_at=datetime.now(UTC).isoformat(),
        )
        self.save(config)
        _logger.info("GitHub runner set up: %s", config.full_name)
        return config

    def _ours(self, api: _Api, owner: str, repo: str) -> bool:
        """Whether a repository already has a VethuQ caller (so setup may refresh it)."""
        current = api.read_file(owner, repo, WORKFLOW_PATH)
        return current is not None and _Caller.pin(current[0]) is not None

    # ----- checking ---------------------------------------------------------------------------

    def check(self, token: str | None) -> tuple[_Config, _Check, Any]:
        config = self.require()
        api = self.api(token)
        problems: list[str] = []
        found = api.repo(config.owner, config.repo)
        if found is None:
            return (
                config,
                _Check(False, None, False, None, None, False, ["The repository is gone."]),
                api,
            )
        caller = api.read_file(config.owner, config.repo, WORKFLOW_PATH)
        pinned = _Caller.pin(caller[0]) if caller else None
        image = _Caller.image(caller[0]) if caller else None
        if caller is None:
            problems.append("The runner workflow is missing.")
        elif pinned is None:
            problems.append("The runner workflow isn't VethuQ's.")
        secret = api.has_secret(config.owner, config.repo, SECRET_NAME)
        if not secret:
            problems.append("The master key secret is missing.")
        if not self.keys().exists():
            problems.append("The master key is missing on this computer.")
        elif _MasterKey.fingerprint(self.keys().read()) != config.key_fingerprint:
            problems.append("The master key on this computer isn't the one set up.")
        if not found.get("private", True):
            problems.append("The repository is public: sizes and timing of jobs are visible.")
        expected = _Caller.render(_Row(config.workflow_ref, config.image, config.protocol, "", ""))
        caller_ok = caller is not None and caller[0] == expected
        if caller and pinned is not None and not caller_ok:
            problems.append("The runner workflow was changed.")
        return (
            config,
            _Check(
                True, bool(found.get("private", True)), caller_ok, pinned, image, secret, problems
            ),
            api,
        )

    # ----- update and remove ------------------------------------------------------------------

    def update(self, token: str | None, workflow_ref: str | None) -> _Config:
        self.gate()
        config = self.require()
        row = _Compatibility.choose(self.client_version, workflow_ref)
        api = self.api(token)
        found = api.repo(config.owner, config.repo)
        if found is None:
            raise _GitHubSetupError(f"{config.full_name} no longer exists.", "Run setup again.")
        self.put_caller(api, config.owner, config.repo, found.get("default_branch") or "main", row)
        key = self.keys().read()
        self.put_secret(api, config.owner, config.repo, key)
        updated = _Config(
            **{**asdict(config), "workflow_ref": row.workflow_ref, "image": row.image,
               "protocol": row.protocol, "private": bool(found.get("private", True))}
        )  # fmt: skip
        self.save(updated)
        return updated

    def remove(self, token: str | None, *, delete_repo: bool, delete_key: bool) -> _Config:
        config = self.require()
        if delete_repo:
            self.api(token).delete_repo(config.owner, config.repo)
        if delete_key:
            self.keys().remove()
        self.forget()
        return config
