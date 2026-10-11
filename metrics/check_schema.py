"""Checks that the batch schema, its examples and the Python client's field lists agree.

Run from the repository root (CI does): needs `jsonschema`, and the `vethuq` package importable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent / "schema" / "v1"


def main() -> int:
    batch = json.loads((ROOT / "batch.schema.json").read_text())
    Draft202012Validator.check_schema(batch)
    validator = Draft202012Validator(batch)
    failed = 0
    for example in sorted((ROOT / "examples").glob("*.json")):
        ok = validator.is_valid(json.loads(example.read_text()))
        expected = example.name.startswith("valid")
        if ok != expected:
            print(f"FAIL {example.name}: expected {'valid' if expected else 'invalid'}")
            failed += 1
    try:
        from vethuq._metrics import ALLOWED
    except ImportError:
        print("vethuq isn't installed; skipping the field-list check")
        return 1 if failed else 0
    props = batch["properties"]
    day = props["days"]["items"]["properties"]
    wanted = {
        "batch": set(props),
        "client": set(props["client"]["properties"]),
        "settings": set(props["settings"]["properties"]),
        "day": set(day),
        "page": set(day["pages"]["items"]["properties"]),
        "failure": set(day["failures"]["items"]["properties"]),
    }
    for kind, fields in wanted.items():
        if fields != ALLOWED[kind]:
            print(f"FAIL {kind}: schema {sorted(fields)} != client {sorted(ALLOWED[kind])}")
            failed += 1
    print("ok" if not failed else f"{failed} problem(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
