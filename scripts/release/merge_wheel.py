"""Build the `vethuq` wheel of one platform: the pure-Python wheel plus the compiled runtime.

    python scripts/release/merge_wheel.py PURE.whl ENTITLEMENTS.whl --out dist/

`PURE.whl` is the `py3-none-any` wheel of `vethuq`; `ENTITLEMENTS.whl` is a `cp311-abi3` platform
wheel of `vethuq-entitlements` (an asset of a private VethuQ-entitlements release). The result holds
everything in the pure wheel and the `vethuq_entitlements` package of the other, is tagged for the
platform (`vethuq-X-cp311-abi3-<platform>.whl`), and has a fresh RECORD. `vethuq` does not depend on
`vethuq-entitlements`: licensed add-ons import `vethuq_entitlements`, and this wheel provides it.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import sys
import zipfile
from pathlib import Path

PACKAGE = "vethuq_entitlements/"


class MergeError(Exception):
    """The two wheels cannot be merged."""


def tags_of(wheel: zipfile.ZipFile) -> list[str]:
    for name in wheel.namelist():
        if name.endswith(".dist-info/WHEEL"):
            return [
                line.split(":", 1)[1].strip()
                for line in wheel.read(name).decode().splitlines()
                if line.startswith("Tag:")
            ]
    raise MergeError("The wheel has no WHEEL file.")


def hashed(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"sha256={digest}"


def merge(pure: Path, entitlements: Path, out_dir: Path) -> Path:
    """Write the merged wheel into `out_dir` and return its path."""
    with zipfile.ZipFile(pure) as base, zipfile.ZipFile(entitlements) as extra:
        base_tags, extra_tags = tags_of(base), tags_of(extra)
        if base_tags != ["py3-none-any"]:
            raise MergeError(f"{pure.name} is not a pure-Python wheel ({base_tags}).")
        if len(extra_tags) != 1 or not extra_tags[0].startswith("cp311-abi3-"):
            raise MergeError(f"{entitlements.name} is not a cp311-abi3 platform wheel.")
        platform = extra_tags[0].removeprefix("cp311-abi3-")
        files: dict[str, bytes] = {}
        for name in base.namelist():
            if name.endswith("/RECORD") or name.endswith("/WHEEL"):
                continue
            files[name] = base.read(name)
        runtime = [n for n in extra.namelist() if n.startswith(PACKAGE) and not n.endswith("/")]
        if not runtime:
            raise MergeError(f"{entitlements.name} has no {PACKAGE.rstrip('/')} package.")
        clashes = sorted(set(files) & set(runtime))
        if clashes:
            raise MergeError(f"Both wheels hold {clashes[0]}.")
        for name in runtime:
            files[name] = extra.read(name)
        dist_info = next(n.split("/")[0] for n in base.namelist() if ".dist-info/" in n)
        wheel_file = (
            "Wheel-Version: 1.0\nGenerator: vethuq release (merge_wheel)\n"
            f"Root-Is-Purelib: false\nTag: cp311-abi3-{platform}\n"
        )
        files[f"{dist_info}/WHEEL"] = wheel_file.encode()
        record = io.StringIO()
        writer = csv.writer(record, lineterminator="\n")
        for name, data in sorted(files.items()):
            writer.writerow([name, hashed(data), len(data)])
        writer.writerow([f"{dist_info}/RECORD", "", ""])
        files[f"{dist_info}/RECORD"] = record.getvalue().encode()
        stem = pure.name.removesuffix("-py3-none-any.whl")
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{stem}-cp311-abi3-{platform}.whl"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as merged:
            for name, data in files.items():
                merged.writestr(name, data)
    return target


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4 or args[2] != "--out":
        print(__doc__, file=sys.stderr)
        return 2
    try:
        target = merge(Path(args[0]), Path(args[1]), Path(args[3]))
    except (MergeError, OSError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
