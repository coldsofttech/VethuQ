"""Checks that the metrics schemas, their examples and the Python client's field lists agree.

Run from anywhere (CI does): `python metrics/schema/check.py`. Needs `jsonschema`; the field-list
check also needs the `vethuq` package importable and is skipped without it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class SchemaCheck:
    """The checks, each returning the problems it found (an empty list means it passed)."""

    VERSION = "v1"
    BATCH = "batch.schema.json"
    DELETE = "delete.schema.json"

    def __init__(self, root: Path | None = None) -> None:
        """`root` is the folder holding the version folders (default: this folder)."""
        self.root = (root or Path(__file__).resolve().parent) / self.VERSION
        self._batch: dict[str, Any] | None = None

    # ----- the schemas -----------------------------------------------------------------------

    def load(self, name: str) -> dict[str, Any]:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    @property
    def batch(self) -> dict[str, Any]:
        if self._batch is None:
            self._batch = self.load(self.BATCH)
        return self._batch

    def check_schemas(self) -> list[str]:
        """Each schema is itself a valid JSON Schema."""
        problems = []
        for name in (self.BATCH, self.DELETE):
            try:
                Draft202012Validator.check_schema(self.load(name))
            except Exception as exc:  # noqa: BLE001 - any failure to read or validate is a problem
                problems.append(f"{name}: {exc}")
        return problems

    # ----- the examples ----------------------------------------------------------------------

    def check_examples(self) -> list[str]:
        """Examples named `valid-*` pass the batch schema and `invalid-*` ones fail it."""
        validator = Draft202012Validator(self.batch)
        problems = []
        examples = sorted((self.root / "examples").glob("*.json"))
        if not examples:
            problems.append("there are no examples")
        for example in examples:
            expected = example.name.startswith("valid")
            if not expected and not example.name.startswith("invalid"):
                problems.append(f"{example.name}: name it valid-* or invalid-*")
                continue
            ok = validator.is_valid(json.loads(example.read_text(encoding="utf-8")))
            if ok != expected:
                problems.append(f"{example.name}: expected {'valid' if expected else 'invalid'}")
        return problems

    # ----- the client ------------------------------------------------------------------------

    def schema_fields(self) -> dict[str, set[str]]:
        """The fields the batch schema allows, by object kind (the names the client uses)."""
        props = self.batch["properties"]
        day = props["days"]["items"]["properties"]
        return {
            "batch": set(props),
            "client": set(props["client"]["properties"]),
            "settings": set(props["settings"]["properties"]),
            "day": set(day),
            "page": set(day["pages"]["items"]["properties"]),
            "failure": set(day["failures"]["items"]["properties"]),
        }

    def check_client(self) -> list[str] | None:
        """The client's list of allowed fields equals the schema's. None if `vethuq` isn't
        importable (nothing to compare)."""
        try:
            from vethuq._metrics import ALLOWED  # noqa: PLC0415
        except ImportError:
            return None
        problems = []
        for kind, fields in self.schema_fields().items():
            if fields != ALLOWED[kind]:
                problems.append(
                    f"{kind}: schema {sorted(fields)} != client {sorted(ALLOWED[kind])}"
                )
        return problems

    # ----- running them ----------------------------------------------------------------------

    def run(self) -> int:
        """Run every check, print what failed, and return the exit code (0 when all passed)."""
        problems = [*self.check_schemas(), *self.check_examples()]
        client = self.check_client()
        if client is None:
            print("vethuq isn't installed; skipping the field-list check")
        else:
            problems += client
        for problem in problems:
            print(f"FAIL {problem}")
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    @classmethod
    def main(cls) -> int:
        return cls().run()


if __name__ == "__main__":
    sys.exit(SchemaCheck.main())
