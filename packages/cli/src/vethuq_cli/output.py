"""Printing results: a table, a key/value panel, or JSON with `--json`."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import Any

from rich.table import Table
from rich.text import Text

from vethuq_cli.console import Theme, console
from vethuq_cli.state import State


def plain(value: Any) -> Any:
    """`value` as JSON-ready data (dataclasses with `to_dict`, enums, tuples)."""
    if hasattr(value, "to_dict"):
        return plain(value.to_dict())
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [plain(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def cell(value: Any) -> str:
    value = plain(value)
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, list):
        return ", ".join(cell(v) for v in value) or "-"
    if isinstance(value, dict):
        return ", ".join(f"{k}={cell(v)}" for k, v in value.items()) or "-"
    return str(value)


def dump(value: Any) -> None:
    console.print_json(json.dumps(plain(value)))


def table(
    rows: Sequence[Any],
    columns: Sequence[str],
    *,
    title: str | None = None,
    empty: str = "Nothing to show.",
    headers: Mapping[str, str] | None = None,
) -> None:
    """A table of `rows` (dataclasses with `to_dict`, or dicts), the given `columns`.

    With `--export` (see `exportable`) it is written to that file instead of being printed."""
    if State.export is not None:
        from vethuq_cli.export import ListExport  # noqa: PLC0415 - export imports this module

        ListExport.write(State.export, rows, columns, headers)
        return
    if State.json:
        dump(list(rows))
        return
    if not rows:
        console.print(empty, style=Theme.DIM)
        return
    grid = Table(title=title, title_justify="left", header_style=Theme.LABEL)
    for column in columns:
        grid.add_column((headers or {}).get(column, column.replace("_", " ")), overflow="fold")
    for row in rows:
        data = plain(row)
        grid.add_row(*(cell(data.get(column)) for column in columns))
    console.print(grid)


def facts(value: Any, *, title: str | None = None, skip: Sequence[str] = ()) -> None:
    """One object as a two-column table of its fields."""
    if State.json:
        dump(value)
        return
    data = plain(value)
    grid = Table.grid(padding=(0, 2))
    for key, item in data.items():
        if key in skip:
            continue
        grid.add_row(Text(key.replace("_", " "), style=Theme.LABEL), Text(cell(item)))
    if title:
        console.print(title, style="bold")
    console.print(grid)


def say(message: str, *, style: str | None = None, data: Any = None) -> None:
    """A one-line outcome; with `--json` it prints `data` (or `{"message": ...}`) instead."""
    if State.json:
        dump(data if data is not None else {"message": message})
    else:
        console.print(message, style=style)


def guarded(func: Callable[..., Any]) -> Callable[..., Any]:
    return func
