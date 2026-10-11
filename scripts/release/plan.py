"""Work out what a release tag releases, and check the wheels built for it.

    python scripts/release/plan.py vethuq-v1.2.0
    python scripts/release/plan.py vethuq-v1.2.0 --wheels dist/*.whl

Tags (one per package, versions independent; `-rcN` is a release candidate, published to TestPyPI):

    vethuq-addon-api-vX.Y.Z   vethuq-addon-api     pure Python
    vethuq-worker-vX.Y.Z      vethuq-worker        pure Python
    vethuq-vX.Y.Z             vethuq               one wheel per platform, with the compiled
                                                   `vethuq_entitlements` runtime built in

The version of a pure package comes from the tag (hatch-vcs), so `--wheels` confirms that what was
built carries it. Prints `key=value` lines; under GitHub Actions they are appended to `$GITHUB_OUTPUT`.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

PACKAGES = {
    # tag prefix: (distribution, directory, platform wheels)
    "vethuq-addon-api": ("vethuq-addon-api", "packages/addon-api", False),
    "vethuq-worker": ("vethuq-worker", "packages/worker", False),
    "vethuq": ("vethuq", "packages/core", True),
}
TAG = re.compile(
    r"^(?P<prefix>vethuq-addon-api|vethuq-worker|vethuq)-v(?P<version>\d+\.\d+\.\d+(?:-?rc\d+)?)$"
)


class ReleaseError(Exception):
    """The tag, or what was built for it, is not right."""


@dataclass(frozen=True)
class Plan:
    dist: str
    directory: str
    version: str  # normalised (PEP 440)
    prerelease: bool
    platform_wheels: bool  # one wheel per platform, with the entitlements runtime inside

    def lines(self) -> list[str]:
        return [
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in asdict(self).items()
        ]


def plan(tag: str) -> Plan:
    match = TAG.match(tag)
    if match is None:
        raise ReleaseError(
            f"{tag!r} is not a release tag. Use vethuq-addon-api-vX.Y.Z, vethuq-worker-vX.Y.Z or "
            "vethuq-vX.Y.Z (add -rcN for a release candidate)."
        )
    dist, directory, platform = PACKAGES[match["prefix"]]
    version = Version(match["version"].replace("-rc", "rc"))
    return Plan(dist, directory, str(version), version.is_prerelease, platform)


def wheel_version(path: str) -> Version:
    """The version in a wheel's file name."""
    parts = Path(path).name.split("-")
    if len(parts) < 5 or not path.endswith(".whl"):
        raise ReleaseError(f"{path!r} is not a wheel file name.")
    try:
        return Version(parts[1])
    except InvalidVersion as exc:
        raise ReleaseError(f"{path!r} has no valid version: {exc}") from exc


def check_wheels(release: Plan, wheels: list[str]) -> None:
    """Every wheel is of this distribution and carries the tag's version."""
    if not wheels:
        raise ReleaseError("Nothing was built.")
    prefix = release.dist.replace("-", "_") + "-"
    for wheel in wheels:
        if not Path(wheel).name.startswith(prefix):
            raise ReleaseError(f"{wheel} is not a {release.dist} wheel.")
        if wheel_version(wheel) != Version(release.version):
            raise ReleaseError(f"{wheel} is version {wheel_version(wheel)}, not {release.version}.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    wheels = args[args.index("--wheels") + 1 :] if "--wheels" in args else None
    try:
        release = plan(args[0])
        if wheels is not None:
            check_wheels(release, wheels)
            print(f"{len(wheels)} wheel(s) carry {release.version}.")
            return 0
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    lines = release.lines()
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
