"""Turning JSON/YAML files into searchable text.

These files already are text, so there is nothing to OCR: they're parsed and
flattened into one `path: value` line per leaf (`server.ports[0]: 8080`), which
makes both the keys and the values findable by `vethuq_core.search`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import yaml

_logger = logging.getLogger(__name__)


class _Pairs(list[tuple[str, Any]]):
    """A JSON object's `(key, value)` pairs, kept as-is so duplicate keys all get indexed."""


@dataclass(frozen=True)
class _Leave:
    """Marks the end of a container on the flatten stack."""

    ident: int


class StructuredText:
    # A parsed document can be far bigger than its file (YAML aliases expand
    # when flattened), so both ends are capped rather than trusting the input.
    MAX_FILE_BYTES = 32 * 1024 * 1024
    MAX_TEXT_CHARS = 64 * 1024 * 1024

    # libyaml's C loader when this PyYAML build has one - several times faster.
    _YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

    _BOMS = (
        (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"),
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    )

    @staticmethod
    def decode(data: bytes) -> str:
        """Decode a file's bytes: by its BOM if it has one, else UTF-8, else Windows-1252.

        Never raises - a file that isn't valid UTF-8 is read as Windows-1252
        (undecodable bytes become U+FFFD) rather than failing to index.
        """
        for bom, encoding in StructuredText._BOMS:
            if data.startswith(bom):
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    break
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("cp1252", errors="replace")

    @staticmethod
    def from_json(text: str) -> str:
        """Flatten a JSON document; raises `ValueError`/`RecursionError` if it isn't valid."""
        return StructuredText.flatten(json.loads(text, object_pairs_hook=_Pairs))

    @staticmethod
    def from_yaml(text: str) -> str:
        """Flatten every document in a YAML stream; raises `yaml.YAMLError` if it isn't valid.

        Loaded with the safe loader, so a YAML tag can never construct arbitrary
        Python objects.
        """
        documents = [
            StructuredText.flatten(document)
            for document in yaml.load_all(text, Loader=StructuredText._YAML_LOADER)
        ]
        return "\n\n".join(documents)

    @staticmethod
    def flatten(root: object) -> str:
        """One `path: value` line per leaf of `root`, in document order.

        Paths join object keys with `.` and list indexes as `[n]`; an empty
        container is kept as `path: {}`/`path: []` so its key stays searchable.
        Walks iteratively (nesting can run to the parser's own recursion limit)
        and skips a container that contains itself (a YAML anchor can).
        """
        lines: list[str] = []
        size = 0
        active: set[int] = set()
        stack: list[tuple[str, object] | _Leave] = [("", root)]
        while stack:
            item = stack.pop()
            if isinstance(item, _Leave):
                active.discard(item.ident)
                continue
            prefix, value = item

            children = StructuredText._children(prefix, value)
            if children is None or not children:
                line = StructuredText._line(prefix, value, children)
                size += len(line) + 1
                if size > StructuredText.MAX_TEXT_CHARS:
                    raise ValueError("too large to index once expanded")
                lines.append(line)
                continue

            if id(value) in active:
                continue
            active.add(id(value))
            stack.append(_Leave(id(value)))
            stack.extend(reversed(children))
        return "\n".join(lines)

    @staticmethod
    def _children(prefix: str, value: object) -> list[tuple[str, object]] | None:
        """`value`'s `(child_path, child)` pairs, or None if it's a scalar."""
        if isinstance(value, dict | _Pairs):
            pairs = value.items() if isinstance(value, dict) else value
            return [(f"{prefix}.{key}" if prefix else str(key), child) for key, child in pairs]
        if isinstance(value, list | tuple):
            return [(f"{prefix}[{index}]", child) for index, child in enumerate(value)]
        if isinstance(value, set | frozenset):
            return StructuredText._children(prefix, sorted(value, key=str))
        return None

    @staticmethod
    def _line(prefix: str, value: object, children: list[tuple[str, object]] | None) -> str:
        if children is None:
            text = StructuredText._scalar(value)
        elif isinstance(value, dict | _Pairs):
            text = "{}"
        else:
            text = "[]"
        return f"{prefix}: {text}" if prefix else text

    @staticmethod
    def _scalar(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        if isinstance(value, datetime | date | time):
            return value.isoformat()
        if isinstance(value, bytes):
            return f"<binary {len(value)} bytes>"
        return str(value)
