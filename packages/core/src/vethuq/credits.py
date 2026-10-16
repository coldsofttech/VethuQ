"""Credits: what reading pages costs and what you have left: `VethuQ().credits`.

One credit is the work of reading one A4 page once, upright, in one language. Pages that need no
OCR (native text), duplicate files and unchanged files cost nothing, and searching is free. The
free local wallet gets a daily allowance (and a one-off starter) that resets at 00:00 UTC; the
rates and limits come from the signed policy. See `docs/credits.md`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vethuq._credits import _Credits
from vethuq._db import _CreditLedger, _Database
from vethuq._errors import _InvalidGrantError
from vethuq.enums import CreditEntryKind, CreditSortBy, SortOrder

__all__ = [
    "CreditBalance",
    "CreditEntry",
    "CreditGrant",
    "CreditUsage",
    "CreditEntryKind",
    "CreditSortBy",
    "Credits",
    "Redeemed",
    "SortOrder",
]


def _getter(grant: Mapping[str, Any] | object) -> Callable[[str], Any]:
    if isinstance(grant, Mapping):
        return grant.get
    return lambda key: getattr(grant, key, None)


def _credits(milli: int | None) -> float | None:
    return None if milli is None else milli / 1000


@dataclass(frozen=True)
class CreditBalance:
    """What a wallet holds now. Amounts are in credits."""

    wallet: str  # for example "local" or "github"
    daily: float  # what is left of today's allowance, with any metrics bonus
    promotional: float  # what is left of a promotion running today
    one_off: float  # starter and licence credits
    total: float  # everything that can be spent: daily, promotional and one-off
    daily_allowance: float  # today's allowance in full, bonus and promotion included
    bonus_active: bool  # the metrics-sharing bonus is part of today's allowance
    bonus: float  # how much of today's allowance it is
    next_reset: str  # UTC, ISO 8601

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class CreditEntry:
    """One movement of credits: a grant, a charge for a page, a refund or an expiry."""

    id: int
    at: str  # UTC, ISO 8601
    wallet: str
    kind: CreditEntryKind
    amount: float
    source_id: int | None
    run_id: int | None
    page_number: int | None
    phase: str | None
    language: str | None
    size_factor: float | None
    rate_card_version: int | None
    note: str | None
    # The file the page is of; a refund made before the file was recorded has none.
    file: str | None = None

    @classmethod
    def _from_model(cls, row: _CreditLedger, file: str | None = None) -> CreditEntry:
        return cls(
            id=row.id,
            at=row.at,
            wallet=row.wallet,
            kind=CreditEntryKind(row.kind.value),
            amount=row.amount_milli / 1000,
            source_id=row.source_id,
            run_id=row.run_id,
            page_number=row.page_number,
            phase=row.phase,
            language=row.language,
            size_factor=_credits(row.size_factor_milli),
            rate_card_version=row.rate_card_version,
            note=row.note,
            file=file,
        )

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["kind"] = self.kind.value
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class CreditGrant:
    """Credits a wallet received: a day's allowance, a promotion, a starter or licence bundle."""

    id: int
    wallet: str
    kind: str  # daily, promo or one_off
    name: str  # a promotion's name, else where the credits came from
    origin: str
    scope: str | None  # an add-on the credits can only be spent on, or None for all work
    amount: float  # what was granted
    remaining: float
    used: float
    granted_at: str  # UTC, ISO 8601
    expires_at: str | None
    expired: bool

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class CreditUsage:
    """What was spent for one day, source or file (charges less refunds)."""

    key: str  # the day (YYYY-MM-DD), the source's id, or the file's path
    source_id: int | None
    credits: float
    pages: int
    last_at: str | None  # the latest movement, UTC, ISO 8601

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class Redeemed:
    """A credit grant from a licence, and whether it was added just now."""

    id: str
    credits: float  # what was added (0 if it had been redeemed before)
    scope: str | None
    expires_at: str | None
    added: bool

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Credits:
    """The local credits wallet and its ledger.

    Not created directly: use `VethuQ().credits`.
    """

    def __init__(
        self,
        database: _Database,
        credits: _Credits,
        estimate: Callable[[int | str | Path | None], tuple[int, int, int, int]],
        wallets: Callable[[], list[str]],
        revoked_keys: Callable[[], frozenset[str]] = frozenset,
    ) -> None:
        self._database = database
        self._credits = credits
        self._revoked_keys = revoked_keys
        self._estimate = estimate
        self._wallets = wallets

    def wallets(self) -> list[str]:
        """The wallets that can be used now: the processing tiers' (`local` is always there) and
        the credit sub-wallets of installed add-ons (`semantic`, once that add-on is installed)."""
        return self._wallets()

    def _wallet(self, wallet: str) -> str:
        name = str(wallet).strip().lower()
        if name not in self._wallets():
            raise ValueError(f"No wallet {wallet!r}. Wallets: {', '.join(self._wallets())}.")
        return name

    def balance(self, wallet: str = "local") -> CreditBalance:
        """What a wallet holds now, brought up to date with today's allowance. `wallet` is one of
        `wallets()`: `local`, `github` once that tier can be used, or an add-on's (`semantic`)."""
        name = self._wallet(wallet)
        with self._database.session() as session:
            balance, _terms, reset = self._credits.balance(session, name)
            base, bonus, promo = self._credits.today_allowance(session, name)
        return CreditBalance(
            wallet=name,
            daily=balance.daily_milli / 1000,
            promotional=balance.promo_milli / 1000,
            one_off=balance.one_off_milli / 1000,
            total=(balance.daily_milli + balance.promo_milli + balance.one_off_milli) / 1000,
            daily_allowance=(base + bonus + promo) / 1000,
            bonus_active=bonus > 0,
            bonus=bonus / 1000,
            next_reset=reset.isoformat(),
        )

    def next_reset(self) -> str:
        """When the daily allowances reset: 00:00 UTC, as an ISO 8601 string."""
        return self.balance().next_reset

    def history(
        self,
        kind: CreditEntryKind | str | None = None,
        source: int | None = None,
        wallet: str | None = None,
        run_id: int | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        sort_by: CreditSortBy | str = CreditSortBy.AT,
        order: SortOrder | str = SortOrder.DESC,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CreditEntry]:
        """The ledger, newest first unless sorted otherwise.

        `kind` keeps one `CreditEntryKind`; `wallet` keeps one wallet; `source` (an id) and
        `run_id` keep what was spent for them; `since` / `until` bound the time (a `datetime`,
        naive meaning UTC, or an ISO 8601 string). Charges for a source are deleted when the
        source is purged. Raises `ValueError`
        for a value that isn't valid.
        """
        name = None if wallet is None else self._wallet(wallet)
        with self._database.session() as session:
            self._credits.sync(session)
            rows = self._credits.history(
                session,
                kind=kind,
                wallet=name,
                source_id=source,
                run_id=run_id,
                since=since,
                until=until,
                sort_by=sort_by,
                order=order,
                limit=limit,
                offset=offset,
            )
            return [
                CreditEntry._from_model(row, self._credits.file_of(row.kind, row.note))
                for row in rows
            ]

    def grants(
        self,
        wallet: str | None = None,
        kind: str | None = None,
        scope: str | None = None,
        include_expired: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CreditGrant]:
        """Every grant of credits, newest first: the daily allowances, promotions, one-off
        starter and licence bundles. `kind` is daily, promo or one_off; `scope` keeps the
        credits that only an add-on can spend. Raises `ValueError` for a value that isn't valid."""
        if kind is not None and kind not in ("daily", "promo", "one_off"):
            raise ValueError("kind is daily, promo or one_off.")
        name = None if wallet is None else self._wallet(wallet)
        with self._database.session() as session:
            self._credits.sync(session)
            rows = self._credits.grants(
                session,
                wallet=name,
                kind=kind,
                scope=scope,
                include_expired=include_expired,
                limit=limit,
                offset=offset,
            )
            return [
                CreditGrant(
                    id=grant.id,
                    wallet=grant.wallet,
                    kind=grant.kind.value,
                    name=name,
                    origin=grant.origin,
                    scope=grant.scope,
                    amount=grant.amount_milli / 1000,
                    remaining=grant.remaining_milli / 1000,
                    used=(grant.amount_milli - grant.remaining_milli) / 1000,
                    granted_at=grant.granted_at,
                    expires_at=grant.expires_at,
                    expired=expired,
                )
                for grant, name, expired in rows
            ]

    def usage(
        self,
        group_by: str = "day",
        wallet: str | None = None,
        source: int | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        sort_by: str = "key",
        order: SortOrder | str = SortOrder.DESC,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CreditUsage]:
        """What was spent, grouped by `day`, `source` or `file`: charges less refunds. `source`
        keeps one source's work; `since` and `until` bound the time; `sort_by` is `key`,
        `credits`, `pages` or `last`. Work for a purged source is gone with it. Raises
        `ValueError` for a value that isn't valid."""
        if group_by not in ("day", "source", "file"):
            raise ValueError("group_by is day, source or file.")
        direction = SortOrder(order).value if isinstance(order, str) else order.value
        name = None if wallet is None else self._wallet(wallet)
        with self._database.session() as session:
            rows = self._credits.usage(
                session,
                group_by=group_by,
                wallet=name,
                source_id=source,
                since=None if since is None else self._credits._moment(since, "since"),
                until=None if until is None else self._credits._moment(until, "until"),
                sort_by=sort_by,
                order=direction,
                limit=limit,
                offset=offset,
            )
        out = []
        for row in rows:
            key, source_id = row["key"], row.get("source_id")
            out.append(
                CreditUsage(
                    key=str(key),
                    source_id=source_id if group_by != "source" else int(key),
                    credits=int(row["milli"] or 0) / 1000,
                    pages=int(row["pages"]),
                    last_at=row["last"],
                )
            )
        return out

    # ----- licence credits --------------------------------------------------------------------

    def redeem(self, grants: Iterable[Mapping[str, Any] | object]) -> list[Redeemed]:
        """Add the credit grants of a verified licence. Each grant is added once, however often
        it is redeemed. A grant has an `id`, an `amount`, and optionally a `scope` (an add-on id)
        and an `expires_at` or `expires` (otherwise the policy's one-off expiry applies).

        Raises `InvalidGrantError` for a grant that is malformed, expired or over the limit on
        one-off credits held.
        """
        done: list[Redeemed] = []
        with self._database.session() as session:
            for grant in grants:
                get = _getter(grant)
                grant_id, amount = get("id"), get("amount")
                if not isinstance(grant_id, str) or not grant_id:
                    raise _InvalidGrantError("A credit grant needs an id.")
                expires = get("expires_at") or get("expires")
                added, milli = self._credits.redeem(
                    session, grant_id, amount, get("scope"), expires
                )
                done.append(
                    Redeemed(
                        id=grant_id,
                        credits=milli / 1000,
                        scope=get("scope") or None,
                        expires_at=expires.isoformat()
                        if isinstance(expires, datetime)
                        else expires,
                        added=added,
                    )
                )
        return done

    def redeem_licence(self, token: str) -> list[Redeemed]:
        """Verify a licence token and redeem its credit grants.

        Needs `vethuq-entitlements`. Raises `InvalidGrantError` if it isn't installed, the
        licence isn't valid, or the policy has revoked it.
        """
        try:
            from vethuq_entitlements import Licences  # noqa: PLC0415
        except ImportError:
            raise _InvalidGrantError(
                "Licences can't be checked here.", "Install vethuq-entitlements."
            ) from None
        revoked = self._credits.policy().get("revoked_licence_ids", [])
        # Revoked signing key ids go in the same list: a runtime that knows about them refuses a
        # licence signed by one, and an older one just never matches.
        licence = Licences().verify(token, revoked=[*revoked, *self._revoked_keys()])
        if not licence.ok:
            raise _InvalidGrantError(f"The licence isn't valid: {licence.detail}.")
        return self.redeem(licence.credit_grants())

    # ----- before a run -----------------------------------------------------------------------

    def estimate(self, target: int | str | Path | None = None) -> CreditEstimate:
        """What indexing would cost now, at most: files not indexed yet (duplicates excluded),
        pages that need OCR priced by size. Reads files but changes nothing."""
        files, pages, ocr_pages, cost = self._estimate(target)
        with self._database.session() as session:
            have = self._credits.balance(session)[0].total_milli
        return CreditEstimate(
            files=files,
            pages=pages,
            ocr_pages=ocr_pages,
            credits=cost / 1000,
            maximum=cost * 1.25 / 1000,
            affordable=cost <= have,
        )


@dataclass(frozen=True)
class CreditEstimate:
    """What indexing a target would cost, from the files as they are now."""

    files: int  # files that would be read
    pages: int  # their pages
    ocr_pages: int  # pages that need OCR
    credits: float  # the cost
    maximum: float  # the most it can cost: a charge is capped at 125% of the estimate
    affordable: bool  # the wallet covers it

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
