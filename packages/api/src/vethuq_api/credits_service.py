"""Credits for the interface: balances per wallet, what was granted, what was spent, the ledger."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

_SORTS = {
    "grants": {"granted_at", "kind", "name", "amount", "used", "remaining", "expires_at"},
    "usage": {"key", "credits", "pages", "last"},
}


def _page(rows: list[Any], offset: int, limit: int) -> list[Any]:
    return rows[offset : offset + limit]


def _name(path: str) -> str:
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return parts[-1] if parts else path


class CreditsService:
    """Reads the core's credits and shapes them for the screens. Filtering, sorting and paging of
    the (small) lists happen here; the ledger, which can be large, is paged by the core."""

    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client

    # ----- balances ---------------------------------------------------------------------------

    def wallets(self) -> list[dict[str, object]]:
        credits = self._client().credits
        out = []
        for name in credits.wallets():
            balance = credits.balance(name).to_dict()
            allowance = float(balance["daily_allowance"])
            left = float(balance["daily"])
            balance["daily_used"] = round(max(allowance - left, 0.0), 3)
            out.append(balance)
        return out

    def summary(self) -> dict[str, object]:
        """The small figure for the status bar: what is left of today's allowance."""
        wallets = self.wallets()
        local = next(
            (w for w in wallets if w["wallet"] == "local"), wallets[0] if wallets else None
        )
        if local is None:
            return {"wallets": [], "primary": None}
        allowance = float(local["daily_allowance"])
        left = float(local["daily"])
        if allowance <= 0:
            level = "ok"
        elif left <= 0:
            level = "empty"
        elif left / allowance < 0.2:
            level = "low"
        else:
            level = "ok"
        return {
            "wallets": [
                {
                    "wallet": w["wallet"],
                    "daily": w["daily"],
                    "daily_allowance": w["daily_allowance"],
                    "total": w["total"],
                }
                for w in wallets
            ],
            "primary": local["wallet"],
            "daily": left,
            "daily_allowance": allowance,
            "total": local["total"],
            "level": level,
            "next_reset": local["next_reset"],
        }

    def totals(self, wallet: str) -> dict[str, object]:
        """Received, consumed, lapsed and remaining for a wallet since it began."""
        credits = self._client().credits
        grants = credits.grants(wallet=wallet)
        received = sum(g.amount for g in grants if g.kind != "grace")
        lapsed = sum(g.remaining for g in grants if g.expired and g.kind != "grace")
        consumed = sum(u.credits for u in credits.usage("day", wallet=wallet))
        balance = credits.balance(wallet)
        return {
            "wallet": wallet,
            "received": round(received, 3),
            "consumed": round(consumed, 3),
            "lapsed": round(lapsed, 3),
            "remaining": balance.total,
        }

    # ----- grants -----------------------------------------------------------------------------

    def grants(
        self,
        *,
        wallet: str | None,
        kind: str | None,
        scope: str | None,
        include_expired: bool,
        q: str,
        sort: str,
        order: str,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        if sort not in _SORTS["grants"]:
            raise ValueError(f"Sort by {', '.join(sorted(_SORTS['grants']))}.")
        rows = [
            g.to_dict()
            for g in self._client().credits.grants(
                wallet=wallet, kind=kind, scope=scope, include_expired=include_expired, limit=5000
            )
        ]
        needle = q.strip().lower()
        if needle:
            rows = [r for r in rows if needle in f"{r['name']} {r['origin']} {r['scope']}".lower()]
        rows.sort(key=lambda r: (r[sort] is None, r[sort]), reverse=order == "desc")
        return {"total": len(rows), "items": _page(rows, offset, limit)}

    # ----- usage ------------------------------------------------------------------------------

    def _source_names(self) -> dict[int, dict[str, str]]:
        sources = self._client().sources.list(include_removed=True)
        return {
            s.id: {
                "name": s.name if hasattr(s, "name") else _name(str(s.path)),
                "path": str(s.path),
            }
            for s in sources
        }

    def usage(
        self,
        *,
        group_by: str,
        wallet: str | None,
        source: int | None,
        since: str | None,
        until: str | None,
        q: str,
        sort: str,
        order: str,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        if sort not in _SORTS["usage"]:
            raise ValueError(f"Sort by {', '.join(sorted(_SORTS['usage']))}.")
        rows = [
            u.to_dict()
            for u in self._client().credits.usage(
                group_by,
                wallet=wallet,
                source=source,
                since=since,
                until=until,
                sort_by=sort,
                order=order,
            )
        ]
        if group_by in ("source", "file"):
            names = self._source_names()
            for row in rows:
                info = names.get(row["source_id"]) if row["source_id"] is not None else None
                row["source"] = info["name"] if info else None
                if group_by == "source":
                    row["name"] = info["name"] if info else f"Source {row['key']}"
                    row["path"] = info["path"] if info else None
                else:
                    row["name"] = _name(str(row["key"]))
                    row["path"] = row["key"]
        needle = q.strip().lower()
        if needle:
            rows = [
                r
                for r in rows
                if needle in f"{r['key']} {r.get('name', '')} {r.get('source', '')}".lower()
            ]
        return {
            "total": len(rows),
            "credits": round(sum(r["credits"] for r in rows), 3),
            "pages": sum(r["pages"] for r in rows),
            "items": _page(rows, offset, limit),
        }

    def daily(self, days: int) -> dict[str, object]:
        """Credits spent on each of the last `days` UTC days, per wallet, empty days included."""
        credits = self._client().credits
        names = credits.wallets()
        today = datetime.now(UTC).date()
        first = today - timedelta(days=days - 1)
        per: dict[str, dict[str, float]] = {}
        for name in names:
            for row in credits.usage("day", wallet=name, since=first.isoformat()):
                per.setdefault(name, {})[row.key] = row.credits
        series = []
        for offset in range(days):
            day: date = first + timedelta(days=offset)
            key = day.isoformat()
            series.append({"day": key, **{n: per.get(n, {}).get(key, 0.0) for n in names}})
        return {"wallets": names, "days": series}

    # ----- ledger -----------------------------------------------------------------------------

    def ledger(
        self,
        *,
        kind: str | None,
        wallet: str | None,
        source: int | None,
        run: int | None,
        since: str | None,
        until: str | None,
        sort: str,
        order: str,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        sort_by = {"amount": "amount_milli"}.get(sort, sort)
        rows = self._client().credits.history(
            kind=kind,
            wallet=wallet,
            source=source,
            run_id=run,
            since=since,
            until=until,
            sort_by=sort_by,
            order=order,
            limit=limit + 1,
            offset=offset,
        )
        return {"items": [r.to_dict() for r in rows[:limit]], "more": len(rows) > limit}

    # ----- licences and export ----------------------------------------------------------------

    def redeem(self, token: str) -> list[dict[str, object]]:
        return [r.to_dict() for r in self._client().credits.redeem_licence(token)]

    @staticmethod
    def export(rows: list[dict[str, Any]], fmt: str, name: str) -> tuple[bytes, str, str]:
        if fmt == "json":
            return json.dumps(rows, indent=2).encode(), f"{name}.json", "application/json"
        if fmt != "csv":
            raise ValueError("format is csv or json.")
        buffer = io.StringIO()
        columns = list(rows[0]) if rows else []
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8-sig"), f"{name}.csv", "text/csv"
