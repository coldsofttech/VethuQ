"""Statistics for the interface: what has been read, in totals and by group."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from vethuq_api.credits_service import CreditsService

GROUPS = ("source", "language", "file_type", "engine", "page_source", "band", "day")
SORTS = ("key", "files", "pages", "ocr_pages", "confidence", "duration_ms", "credits", "failures")
# The days a chart shows when no period is chosen.
CHART_DAYS = 60


class StatsService:
    """Reads the core's statistics. The core totals, sorts and filters; this pages and shapes."""

    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client

    @staticmethod
    def _filters(args: dict[str, Any]) -> dict[str, Any]:
        """The filters the core's overview takes, from what the interface sends."""
        source = args.get("source")
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        return {
            "source": source or None,
            "language": args.get("language") or None,
            "file_type": args.get("file_type") or None,
            "engine": args.get("engine") or None,
            "page_source": args.get("page_source") or None,
            "band": args.get("band") or None,
            "since": args.get("since") or None,
            "until": args.get("until") or None,
        }

    def summary(self, **args: Any) -> dict[str, object]:
        """The totals for the filters, and the pages read on each day (empty days included)."""
        stats = self._client().stats
        filters = self._filters(args)
        overview = stats.overview("day", sort_by="key", order="asc", **filters)
        per_day = {row.key: row for row in overview.rows}
        today = datetime.now(UTC).date()
        last = date.fromisoformat(filters["until"][:10]) if filters["until"] else today
        if filters["since"]:
            first = date.fromisoformat(filters["since"][:10])
        else:
            first = last - timedelta(days=CHART_DAYS - 1)
            if per_day and min(per_day) > first.isoformat():
                first = max(date.fromisoformat(min(per_day)), first)
        days = []
        cursor = first
        while cursor <= last and len(days) < 800:
            row = per_day.get(cursor.isoformat())
            days.append(
                {
                    "day": cursor.isoformat(),
                    "native": row.native_pages if row else 0,
                    "ocr": row.ocr_pages if row else 0,
                }
            )
            cursor += timedelta(days=1)
        return {"total": overview.total.to_dict(), "days": days}

    def breakdown(
        self,
        *,
        group_by: str,
        sort: str,
        order: str,
        offset: int,
        limit: int,
        **args: Any,
    ) -> dict[str, object]:
        if group_by not in GROUPS:
            raise ValueError(f"Group by {', '.join(GROUPS)}.")
        if sort not in SORTS:
            raise ValueError(f"Sort by {', '.join(SORTS)}.")
        if order not in ("asc", "desc"):
            raise ValueError("order is asc or desc.")
        overview = self._client().stats.overview(
            group_by,
            sort_by=sort,
            order=order,
            limit=limit + 1,
            offset=offset,
            **self._filters(args),
        )
        rows = [row.to_dict() for row in overview.rows]
        return {
            "totals": overview.total.to_dict(),
            "items": rows[:limit],
            "more": len(rows) > limit,
        }

    def names(self) -> dict[int, str]:
        """Source ids and paths, so a row for a source can be opened."""
        return {s.id: str(s.path) for s in self._client().sources.list(include_removed=True)}

    def source_ids(self) -> dict[str, int]:
        return {path: source_id for source_id, path in self.names().items()}

    @staticmethod
    def export(rows: list[dict[str, Any]], fmt: str) -> tuple[bytes, str, str]:
        flat = [{k: v for k, v in r.items() if k != "bands"} | _bands(r) for r in rows]
        return CreditsService.export(flat, fmt, "statistics")


def _bands(row: dict[str, Any]) -> dict[str, int]:
    return {f"pages_{name}": count for name, count in (row.get("bands") or {}).items()}
