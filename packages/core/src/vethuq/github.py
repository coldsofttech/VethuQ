"""Running OCR in your own GitHub account: `VethuQ().github`.

`setup()` creates a private repository you own (or uses one), puts VethuQ's thin caller workflow in
it, and gives it a master key as a secret. Later, VethuQ encrypts the pages that need OCR, hands
them to that repository, and a GitHub Actions job processes them; results come back encrypted.
Pages with a text layer never leave your computer.

You need a GitHub token (fine-grained, limited to the runner repository once it exists). Pass
`token=...` or set `VETHUQ_GITHUB_TOKEN`; it is used for the call and never stored. To create the
repository the token also needs the *Administration* permission (or create the repository yourself
and pass `create=False`); to write the workflow it needs *Workflows*; and *Contents*, *Actions*
and *Secrets* (read and write) for the rest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from vethuq._github import _Check, _Compatibility, _Config, _Runner

__all__ = ["GitHub", "GitHubRunner", "GitHubStatus", "GitHubVersion"]


@dataclass(frozen=True)
class GitHubRunner:
    """The runner repository VethuQ set up."""

    owner: str
    repo: str
    private: bool
    workflow_ref: str  # the VethuQ workflow tag the caller is pinned to
    image: str  # the worker image it runs
    protocol: int  # the job protocol version
    key_fingerprint: str  # tells master keys apart; the key itself is never shown
    set_up_at: str  # UTC, ISO 8601

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"

    @classmethod
    def _from_config(cls, config: _Config) -> GitHubRunner:
        return cls(
            owner=config.owner,
            repo=config.repo,
            private=config.private,
            workflow_ref=config.workflow_ref,
            image=config.image,
            protocol=config.protocol,
            key_fingerprint=config.key_fingerprint,
            set_up_at=config.set_up_at,
        )

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["url"] = self.url
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class GitHubStatus:
    """The runner repository as it is on GitHub now."""

    runner: GitHubRunner
    repo_found: bool
    private: bool | None  # its visibility now
    caller_ok: bool  # the workflow is VethuQ's and unchanged
    pinned_ref: str | None  # what it is pinned to now
    secret_set: bool  # the master key secret is there
    up_to_date: bool  # it is on the newest version this VethuQ allows
    ok: bool  # nothing is wrong
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["runner"] = self.runner.to_dict()
        data["problems"] = list(self.problems)
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class GitHubVersion:
    """A runner version this VethuQ may set up."""

    workflow_ref: str
    image: str
    protocol: int
    min_client: str
    status: str  # provisional, released or withdrawn

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class GitHub:
    """Set up and look after the GitHub runner repository.

    Not created directly: use `VethuQ().github`. Every method that talks to GitHub takes a
    `token`; left out, `VETHUQ_GITHUB_TOKEN` (then `GITHUB_TOKEN`) is used. The policy can switch
    the tier off (`GitHubUnavailableError`).
    """

    def __init__(self, runner: _Runner) -> None:
        self._runner = runner

    def setup(
        self,
        repo: str = "vethuq-runner",
        *,
        owner: str | None = None,
        private: bool = True,
        token: str | None = None,
        master_key: str | bytes | None = None,
        workflow_ref: str | None = None,
        create: bool = True,
        adopt: bool = False,
    ) -> GitHubRunner:
        """Create (or use) the runner repository, add the caller workflow and the master key, and
        remember it.

        `repo` is the repository's name and `owner` the user or organization (default: the
        token's user). It is created `private` (public repositories expose job sizes and timing
        and have a lower free allowance). `master_key` restores an existing key (as printed
        base64); left out, the one already kept on this computer is reused, or a new one is made
        in your data folder. `workflow_ref` picks one of `versions()` (default: the newest).
        `create=False` requires the repository to exist; one that wasn't set up by VethuQ is
        refused unless `adopt=True`. Running it again repairs and refreshes the runner.

        Raises `GitHubUnavailableError`, `GitHubAuthError` (no, rejected or too weak a token) and
        `GitHubSetupError` (anything else that stops it).
        """
        config = self._runner.setup(
            repo,
            owner=owner,
            private=private,
            token=token,
            master_key=master_key,
            workflow_ref=workflow_ref,
            create=create,
            adopt=adopt,
        )
        return GitHubRunner._from_config(config)

    def runner(self) -> GitHubRunner | None:
        """The runner that was set up, or None. Makes no request."""
        config = self._runner.config()
        return GitHubRunner._from_config(config) if config else None

    def status(self, token: str | None = None) -> GitHubStatus:
        """Check the repository on GitHub: that it exists, the workflow is VethuQ's and unchanged,
        the secret is set, and the version is current. Raises `GitHubNotSetUpError` if there is no
        runner."""
        config, check, _ = self._runner.check(token)
        return self._status(config, check)

    def _status(self, config: _Config, check: _Check) -> GitHubStatus:
        newest = _Compatibility.choose(self._runner.client_version)
        problems = list(check.problems)
        up_to_date = check.pinned_ref == newest.workflow_ref
        if check.caller_ok and not up_to_date:
            problems.append(f"A newer runner is available: {newest.workflow_ref}.")
        blocking = [p for p in problems if not p.startswith("A newer") and "public" not in p]
        return GitHubStatus(
            runner=GitHubRunner._from_config(config),
            repo_found=check.repo_found,
            private=check.private,
            caller_ok=check.caller_ok,
            pinned_ref=check.pinned_ref,
            secret_set=check.secret_set,
            up_to_date=up_to_date,
            ok=check.repo_found and not blocking,
            problems=problems,
        )

    def update(self, token: str | None = None, workflow_ref: str | None = None) -> GitHubRunner:
        """Move the runner to a version this VethuQ allows (default: the newest): rewrites the
        caller workflow's pin and image and refreshes the secret. Raises `GitHubNotSetUpError`
        if there is no runner."""
        return GitHubRunner._from_config(self._runner.update(token, workflow_ref))

    def remove(
        self, token: str | None = None, *, delete_repo: bool = False, delete_key: bool = False
    ) -> GitHubRunner:
        """Forget the runner. The repository is left alone unless `delete_repo=True` (the token
        then needs permission to delete it), and the master key is kept unless `delete_key=True`;
        without the key, results of past jobs can't be read. Returns what was removed."""
        return GitHubRunner._from_config(
            self._runner.remove(token, delete_repo=delete_repo, delete_key=delete_key)
        )

    def versions(self) -> list[GitHubVersion]:
        """The runner versions this VethuQ may set up, oldest first."""
        return [
            GitHubVersion(r.workflow_ref, r.image, r.protocol, r.min_client, r.status)
            for r in _Compatibility.rows()
            if r.usable_by(self._runner.client_version)
        ]
