"""Moving a database from an older schema version to the current one."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection


class _Migration:
    # The step that brings a database up to each schema version, keyed by that version. Version 1
    # is the first schema, so it has none; add `{2: step}` when the schema first changes.
    STEPS: dict[int, Callable[[Connection], None]] = {}

    @staticmethod
    def run(connection: Connection, from_version: int, to_version: int) -> None:
        """Apply, in order, the steps for every version after `from_version` up to `to_version`."""
        for version in range(from_version + 1, to_version + 1):
            step = _Migration.STEPS.get(version)
            if step is not None:
                step(connection)
