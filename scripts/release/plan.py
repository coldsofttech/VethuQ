"""Work out what a release tag releases, and check the wheels built for it.

    python scripts/release/plan.py vethuq-v1.2.0
    python scripts/release/plan.py vethuq-v1.2.0 --wheels dist/*.whl

Tags (one per package, versions independent; `-rcN` is a release candidate, published to TestPyPI):

    vethuq-addon-api-vX.Y.Z   vethuq-addon-api     pure Python
    vethuq-worker-vX.Y.Z      vethuq-worker        pure Python
    vethuq-vX.Y.Z             vethuq               one wheel per platform, with the compiled
                                                   `vethuq_entitlements` runtime built in
    vethuq-cli-vX.Y.Z         vethuq-cli           not on PyPI: release-cli.yml builds the
                                                   installers (Windows .exe, Linux .deb)
    vethuq-worker-bin-vX.Y.Z   the program      not on PyPI: release-worker.yml builds its
                                                   installers (they need the CLI)
    vethuq-addon-<name>-vX.Y.Z   an add-on     not on PyPI: release-add-on.yml builds its installers
                                                   (sources: VethuQ-premium)
    vethuq-bundle-<name>-vX.Y.Z   a bundle     not on PyPI: release-bundle.yml builds its installer
    vethuq-background-service-vX.Y.Z   the service   not on PyPI: release-background-service.yml
                                                   builds its installers (they need the CLI)
    vethuq-desktop-vX.Y.Z           the app         not on PyPI: release-desktop.yml builds its
                                                   Windows installer, which needs the CLI installed
    vethuq-interactive-cli-vX.Y.Z   the shell        not on PyPI: release-interactive-cli.yml builds
                                                   its installers, which need the CLI installed

The version of a pure package comes from the tag (hatch-vcs), so `--wheels` confirms that what was
built carries it. Prints `key=value` lines; under GitHub Actions they also go to `$GITHUB_OUTPUT`.
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
    "vethuq-cli": ("vethuq-cli", "packages/cli", False),
    "vethuq-interactive-cli": ("vethuq-interactive-cli", "packages/interactive-cli", False),
    "vethuq-desktop": ("vethuq-desktop", "packages/desktop", False),
    "vethuq-background-service": ("vethuq-background", "packages/background", False),
    # `vethuq-worker-vX.Y.Z` releases the PyPI package; this one builds the worker program.
    "vethuq-worker-bin": ("vethuq-worker", "packages/worker", False),
    "vethuq": ("vethuq", "packages/core", True),
}
TAG = re.compile(
    r"^(?P<prefix>vethuq-addon-api|vethuq-worker-bin|vethuq-worker|vethuq-interactive-cli|vethuq-desktop|vethuq-background-service|vethuq-cli|vethuq)-v(?P<version>\d+\.\d+\.\d+(?:-?rc\d+)?)$"
)


# `vethuq-addon-<name>-vX.Y.Z` builds the installers of one add-on (sources: VethuQ-premium).
# `api` is the add-on API package, released as a Python package under its own tag above.
ADDON_TAG = re.compile(
    r"^vethuq-addon-(?P<name>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)"
    r"-v(?P<version>\d+\.\d+\.\d+(?:-?rc\d+)?)$"
)
BUNDLE_TAG = re.compile(
    r"^vethuq-bundle-(?P<name>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)"
    r"-v(?P<version>\d+\.\d+\.\d+(?:-?rc\d+)?)$"
)
NOT_ADDONS = frozenset({"api", "core", "test", "tests", "template", "sample"})


class ReleaseError(Exception):
    """The tag, or what was built for it, is not right."""


@dataclass(frozen=True)
class Plan:
    dist: str
    directory: str
    version: str  # normalised (PEP 440)
    prerelease: bool
    platform_wheels: bool  # one wheel per platform, with the entitlements runtime inside
    name: str = (
        ""  # an add-on's or bundle's name (`vethuq-addon-<name>`); empty for the packages above
    )
    kind: str = ""  # "add-on" or "bundle"; empty for the packages above

    def lines(self) -> list[str]:
        return [
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in asdict(self).items()
        ]


def plan(tag: str) -> Plan:
    match = TAG.match(tag)
    addon = ADDON_TAG.match(tag)
    bundle = BUNDLE_TAG.match(tag)
    if match is None and bundle is not None:
        version = Version(bundle["version"].replace("-rc", "rc"))
        name = bundle["name"]
        return Plan(
            f"vethuq-bundle-{name}",
            "",
            str(version),
            version.is_prerelease,
            False,
            name=name,
            kind="bundle",
        )
    if match is None and addon is not None and addon["name"] not in NOT_ADDONS:
        version = Version(addon["version"].replace("-rc", "rc"))
        name = addon["name"]
        return Plan(
            f"vethuq-addon-{name}",
            "",
            str(version),
            version.is_prerelease,
            False,
            name=name,
            kind="add-on",
        )
    if match is None:
        raise ReleaseError(
            f"{tag!r} is not a release tag. Use vethuq-addon-api-vX.Y.Z, vethuq-worker-vX.Y.Z, "
            "vethuq-cli-vX.Y.Z, vethuq-interactive-cli-vX.Y.Z, vethuq-background-service-vX.Y.Z, "
            "vethuq-desktop-vX.Y.Z, vethuq-addon-<name>-vX.Y.Z, vethuq-bundle-<name>-vX.Y.Z "
            "or vethuq-vX.Y.Z "
            "(add -rcN for a release candidate)."
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
