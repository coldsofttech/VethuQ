#!/usr/bin/env python3
"""Choose which policy keys and URLs a build trusts, by rewriting `vethuq/_policy/embedded.py`.

    python scripts/release/embed_policy.py --flavour production --keys-dir policy/keys
    python scripts/release/embed_policy.py --flavour test \
        --keys-dir ../VethuQ-entitlements/testkit/policy/keys
    python scripts/release/embed_policy.py --flavour development   # no keys: the committed state

A keys directory holds one `<kid>.pub` per key (unpadded base64url raw Ed25519 public key), as the
policy repo publishes them. The flavour decides what is accepted, so a test key cannot slip into a
release and a production key cannot be mistaken for a test one:

- `production`: ids `pol-<16 hex>` (current) and `pst-<16 hex>` (standby) only, at least one of
  each, the three default https URLs.
- `test`: ids `test-pol-...` and `test-pst-...` only, the test policy location.
- `development`: no keys.

A key id must be derived from its key (the first 16 hex digits of SHA-256 of the raw key), so a
mislabelled or damaged file is caught here and not by a client in the field.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "packages/core/src/vethuq/_policy/embedded.py"

PRODUCTION_URLS = (
    "https://coldsofttech.github.io/vethuq/policy/v1/policy.json",
    "https://cdn.jsdelivr.net/gh/coldsofttech/vethuq@main/policy/v1/policy.json",
    "https://raw.githubusercontent.com/coldsofttech/vethuq/main/policy/v1/policy.json",
)
TEST_URLS = ("https://coldsofttech.github.io/vethuq/policy/test/v1/policy.json",)

FLAVOURS = ("development", "test", "production")
KID_RE = {
    "production": re.compile(r"^(?P<role>pol|pst)-(?P<hash>[0-9a-f]{16})$"),
    "test": re.compile(r"^test-(?P<role>pol|pst)-(?P<hash>[0-9a-f]{16})$"),
}

HEADER = '''"""What this build trusts and where it looks: the policy URLs and the public keys.

This file is REWRITTEN BY THE BUILD (`scripts/release/embed_policy.py`); do not edit it by hand.
Flavour: {flavour}. See the committed version of this file for what each flavour means.
"""
'''


class EmbedError(Exception):
    pass


def _raw(kid: str, text: str) -> bytes:
    text = text.strip()
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise EmbedError(f"{kid}: not base64url") from exc
    if len(raw) != 32:
        raise EmbedError(f"{kid}: a public key is 32 bytes, this is {len(raw)}")
    return raw


def read_keys(directory: Path, flavour: str) -> tuple[dict[str, str], dict[str, str]]:
    """`(current, standby)` keys of the directory, checked against the flavour."""
    pattern = KID_RE[flavour]
    current: dict[str, str] = {}
    standby: dict[str, str] = {}
    files = sorted(directory.glob("*.pub"))
    if not files:
        raise EmbedError(f"no .pub files in {directory}")
    for path in files:
        kid, text = path.stem, path.read_text(encoding="utf-8").strip()
        match = pattern.match(kid)
        if match is None:
            other = "a test" if kid.startswith("test-") else "an unexpected"
            raise EmbedError(f"{kid}: {other} key id in a {flavour} build")
        if hashlib.sha256(_raw(kid, text)).hexdigest()[:16] != match["hash"]:
            raise EmbedError(f"{kid}: the id does not match the key")
        (standby if match["role"] == "pst" else current)[kid] = text
    if not current:
        raise EmbedError(f"a {flavour} build needs at least one policy key (pol-...)")
    if not standby:
        raise EmbedError(f"a {flavour} build needs a standby key (pst-...): rotation depends on it")
    return current, standby


def render(flavour: str, current: dict[str, str], standby: dict[str, str]) -> str:
    urls = {"development": (), "test": TEST_URLS, "production": PRODUCTION_URLS}[flavour]
    lines = [HEADER.format(flavour=flavour), f"FLAVOUR = {flavour!r}\n"]
    lines.append("POLICY_URLS: tuple[str, ...] = (")
    lines += [f"    {url!r}," for url in urls]
    lines.append(")\n")
    for name, keys in (("POLICY_KEYS", current), ("POLICY_STANDBY_KEYS", standby)):
        lines.append(f"{name}: dict[str, str] = {{")
        lines += [f"    {kid!r}: {text!r}," for kid, text in sorted(keys.items())]
        lines.append("}\n")
    return "\n".join(lines)


def build(flavour: str, keys_dir: Path | None) -> str:
    if flavour == "development":
        if keys_dir is not None:
            raise EmbedError("a development build embeds no keys; drop --keys-dir")
        return render(flavour, {}, {})
    if keys_dir is None:
        raise EmbedError(f"a {flavour} build needs --keys-dir")
    return render(flavour, *read_keys(keys_dir, flavour))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--flavour", choices=FLAVOURS, required=True)
    parser.add_argument("--keys-dir", type=Path)
    parser.add_argument("--out", type=Path, default=TARGET)
    args = parser.parse_args(argv)
    try:
        text = build(args.flavour, args.keys_dir)
    except EmbedError as exc:
        print(f"embed_policy: {exc}", file=sys.stderr)
        return 1
    args.out.write_text(text, encoding="utf-8")
    print(f"embedded the {args.flavour} policy trust set into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
