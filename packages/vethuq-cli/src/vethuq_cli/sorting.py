"""The `--sort` and `--sort-by` options the listing commands share."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

import typer
from vethuq_core.sorting import Sorting


class SortOptions:
    """Typer annotations for `--sort` (asc or desc) and each list's `--sort-by` columns.

    Leaving both off keeps the list in its usual order; `--sort` alone sorts by the first
    column. `--sort_by` is accepted as a spelling of `--sort-by`.
    """

    ORDER = Annotated[
        Sorting.Order | None,
        typer.Option(
            "--sort", help="Sort order: asc or desc (by the first column unless --sort-by)."
        ),
    ]

    @staticmethod
    def by(columns: type[StrEnum], help_: str) -> Any:
        return Annotated[columns | None, typer.Option("--sort-by", "--sort_by", help=help_)]

    JOBS = by(Sorting.JobBy, "Sort by id, status, kind, target or queued.")
    RUNS = by(Sorting.RunBy, "Sort by id, started, mode, target or status.")
    FILES = by(Sorting.FileBy, "Sort by file, status, confidence or duration.")
    CATALOG = by(Sorting.CatalogBy, "Sort by name, package or status.")
    MODELS = by(Sorting.ModelBy, "Sort by model, size or status.")
