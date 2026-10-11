"""The caller workflow and the table of runner versions VethuQ may set up."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources

from packaging.version import InvalidVersion, Version

from vethuq._errors import _GitHubSetupError

WORKFLOW_PATH = ".github/workflows/vethuq-ocr.yml"
README_PATH = "README.md"
SECRET_NAME = "VETHUQ_MASTER_KEY"  # noqa: S105 - the secret's name, not its value
REUSABLE = "coldsofttech/VethuQ/.github/workflows/github-ocr.yml"


@dataclass(frozen=True)
class _Row:
    workflow_ref: str
    image: str
    protocol: int
    min_client: str
    status: str  # provisional, released or withdrawn

    def usable_by(self, client_version: str) -> bool:
        if self.status == "withdrawn":
            return False
        try:
            return Version(client_version) >= Version(self.min_client)
        except InvalidVersion:
            return True


class _Compatibility:
    """The combinations of workflow tag, image and job protocol that may be set up. The key sits
    in the image's hands, so nothing outside this table is ever written to a runner repository."""

    @staticmethod
    def rows() -> list[_Row]:
        text = resources.files("vethuq._github").joinpath("compatibility.json").read_text("utf-8")
        return [_Row(**row) for row in json.loads(text)["rows"]]

    @staticmethod
    def choose(client_version: str, workflow_ref: str | None = None) -> _Row:
        """The newest usable row, or the usable one named `workflow_ref`."""
        usable = [r for r in _Compatibility.rows() if r.usable_by(client_version)]
        if workflow_ref is not None:
            row = next((r for r in usable if r.workflow_ref == workflow_ref), None)
            if row is None:
                known = ", ".join(r.workflow_ref for r in usable) or "none"
                raise _GitHubSetupError(
                    f"{workflow_ref!r} isn't a runner version this VethuQ may set up.",
                    f"Allowed: {known}.",
                )
            return row
        if not usable:
            raise _GitHubSetupError(
                "No runner version is available for this VethuQ yet.",
                "Update VethuQ, or try again after the next release.",
            )
        return usable[-1]


class _Caller:
    PIN_RE = re.compile(
        r"^\s*uses:\s*" + re.escape(REUSABLE) + r"@(?P<ref>[A-Za-z0-9._/-]+)\s*$", re.MULTILINE
    )
    IMAGE_RE = re.compile(r"^\s*image:\s*(?P<image>\S+)\s*$", re.MULTILINE)

    @staticmethod
    def template(name: str) -> str:
        return resources.files("vethuq._github").joinpath("templates", name).read_text("utf-8")

    @staticmethod
    def render(row: _Row) -> str:
        """The caller workflow for a runner version."""
        text = _Caller.template("vethuq-ocr.yml")
        return text.replace("__WORKFLOW_REF__", row.workflow_ref).replace("__IMAGE__", row.image)

    @staticmethod
    def pin(text: str) -> str | None:
        """The workflow tag a caller is pinned to (None if it isn't ours)."""
        found = _Caller.PIN_RE.search(text)
        return found.group("ref") if found else None

    @staticmethod
    def image(text: str) -> str | None:
        found = _Caller.IMAGE_RE.search(text)
        return found.group("image") if found else None
