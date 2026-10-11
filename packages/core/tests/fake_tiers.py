"""Add-ons that provide processing tiers, for tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from vethuq_addon_api import Addon, Manifest, OcrExecutor, TierSpec
from vethuq_addon_api.testing import FakeExecutor


@dataclass
class State:
    github_available: bool = True
    github_reason: str = ""
    github_executor: OcrExecutor | None = field(
        default_factory=lambda: FakeExecutor(asynchronous=True)
    )
    cloud: FakeExecutor = field(default_factory=lambda: FakeExecutor(default="read in the cloud"))
    extra: list[TierSpec] = field(default_factory=list)


STATE = State()


def reset() -> None:
    STATE.__dict__.update(State().__dict__)


class FakeGithubAddon(Addon):
    """Provides `github` (asynchronous, so a run refuses it for now) and `cloud` (synchronous,
    paid from the github wallet, so it can be run end to end)."""

    manifest = Manifest(id="github", name="vethuq-addon-github", version="0.1.0")

    def processing_tiers(self):
        return [
            TierSpec(
                "github",
                "GitHub",
                "github",
                STATE.github_executor,
                available=STATE.github_available,
                reason=STATE.github_reason,
            ),
            TierSpec("cloud", "Cloud", "github", STATE.cloud),
            *STATE.extra,
        ]


def install(folder: Path) -> None:
    dist = folder / "vethuq_addon_github-0.1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: vethuq_addon_github\nVersion: 0.1.0\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(
        "[vethuq.addons]\ngithub = tests.fake_tiers:FakeGithubAddon\n", encoding="utf-8"
    )
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
