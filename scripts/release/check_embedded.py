#!/usr/bin/env python3
"""Fail a release that would ship a test key, a test URL or no standby key.

    python scripts/release/check_embedded.py                     # the source tree's embedded.py
    python scripts/release/check_embedded.py --wheel dist/*.whl  # what a built wheel really holds

A release must embed the `production` trust set: policy keys `pol-<hex>`, at least one standby
`pst-<hex>`, https URLs, and nowhere any `test-<role>-<hex>` key id or `/test/` policy location.
The wheel check also scans every Python file in the wheel, so a test key pasted somewhere else is
caught too. Exit code 0 is a clean release.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

EMBEDDED = "vethuq/_policy/embedded.py"
DEFAULT_MODULE = Path(__file__).resolve().parents[2] / "packages/core/src" / EMBEDDED

TEST_KEY_ID = re.compile(r"\btest-[a-z]{3}-[0-9a-f]{16}\b")
TEST_URL = re.compile(r"/policy/test/|/test/v1/")
PROD_KEY_ID = re.compile(r"^(pol|pst)-[0-9a-f]{16}$")


def parse(source: str) -> dict:
    """The module's names, read by executing it in an empty namespace (it is plain literals)."""
    names: dict = {}
    exec(compile(source, EMBEDDED, "exec"), names)  # noqa: S102 - our own generated literals
    return names


def problems_in_module(source: str) -> list[str]:
    found: list[str] = []
    try:
        names = parse(source)
    except Exception as exc:  # noqa: BLE001
        return [f"{EMBEDDED} cannot be read: {exc}"]
    if names.get("FLAVOUR") != "production":
        found.append(f"flavour is {names.get('FLAVOUR')!r}, a release embeds 'production'")
    current, standby = names.get("POLICY_KEYS", {}), names.get("POLICY_STANDBY_KEYS", {})
    for kid in [*current, *standby]:
        if kid.startswith("test-") or not PROD_KEY_ID.match(kid):
            found.append(f"key id {kid!r} is not a production key id")
    if any(not kid.startswith("pol-") for kid in current):
        found.append("POLICY_KEYS holds a key that is not a pol- key")
    if any(not kid.startswith("pst-") for kid in standby):
        found.append("POLICY_STANDBY_KEYS holds a key that is not a pst- key")
    if not current:
        found.append("no policy key is embedded")
    if not standby:
        found.append("no standby key is embedded: key rotation would need a new release")
    urls = names.get("POLICY_URLS", ())
    if not urls:
        found.append("no policy URLs are embedded")
    for url in urls:
        if not url.startswith("https://") or TEST_URL.search(url):
            found.append(f"policy URL {url} is not a production https location")
    return found


def problems_in_text(name: str, text: str) -> list[str]:
    found = [f"{name}: test key id {m}" for m in sorted(set(TEST_KEY_ID.findall(text)))]
    found += [f"{name}: test policy location" for _ in TEST_URL.findall(text)[:1]]
    return found


def check_wheel(path: Path) -> list[str]:
    found: list[str] = []
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if EMBEDDED not in names:
            return [f"{path.name}: {EMBEDDED} is missing"]
        found += [f"{path.name}: {p}" for p in problems_in_module(wheel.read(EMBEDDED).decode())]
        for name in names:
            if name.endswith(".py") and name != EMBEDDED:
                text = wheel.read(name).decode("utf-8", "replace")
                found += [f"{path.name}!{p}" for p in problems_in_text(name, text)]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wheel", type=Path, nargs="*", help="built wheels to inspect")
    parser.add_argument("--module", type=Path, default=DEFAULT_MODULE)
    args = parser.parse_args(argv)
    if args.wheel:
        found = [p for wheel in args.wheel for p in check_wheel(wheel)]
    else:
        found = [f"{args.module}: {p}" for p in problems_in_module(args.module.read_text("utf-8"))]
    for line in found:
        print(f"check_embedded: {line}", file=sys.stderr)
    if not found:
        print("check_embedded: a production trust set, no test keys or URLs")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
