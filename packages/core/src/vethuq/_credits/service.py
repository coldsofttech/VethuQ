"""The credits service: terms for the day, the local wallet, charging pages, the ledger."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vethuq._credits.clock import _Clock
from vethuq._credits.pricing import _PageTooLarge, _Pricing
from vethuq._credits.terms import _Terms, milli
from vethuq._credits.wallet import LOCAL, _Balance, _Wallet, next_midnight
from vethuq._db import _CreditGrant, _CreditLedger, _Database, _IndexRun
from vethuq._db.values import _LedgerKind
from vethuq._errors import _InvalidGrantError
from vethuq._settings import _MetricsSettings, _Settings
from vethuq.enums import CreditEntryKind, CreditSortBy, SortOrder


class _Credits:
    TERMS_KEY = "credits_terms"
    BONUS_LAPSE_DAYS = 7
    _logger = logging.getLogger("vethuq.credits")

    def __init__(
        self,
        database: _Database,
        policy: Callable[[], Mapping[str, Any]],
        client_version: str,
    ) -> None:
        self.database = database
        self.policy = policy
        self.client_version = client_version
        self.wallets: dict[str, _Wallet] = {LOCAL: _Wallet(LOCAL)}
        self.wallet = self.wallets[LOCAL]  # the local wallet

    # ----- the day's terms --------------------------------------------------------------------

    def terms(self, session: Session) -> _Terms:
        """The rates and limits for today. A policy change applies from the next UTC day: today
        keeps what it started with (and a policy with a later `effective_from` waits for it)."""
        today = _Clock.today(session)
        stored = _Settings.get(session, self.TERMS_KEY)
        kept: tuple[str, _Terms] | None = None
        if stored:
            try:
                data = json.loads(stored)
                kept = (data["day"], _Terms.from_dict(data["terms"]))
            except (ValueError, KeyError, TypeError):
                kept = None
        if kept and kept[0] == today.isoformat():
            return kept[1]
        raw = self.policy()
        effective = raw.get("effective_from")
        if kept and isinstance(effective, str) and effective > today.isoformat():
            terms = kept[1]  # not in force yet
        else:
            terms = _Terms.from_policy(raw, self.client_version)
        _Settings.set(
            session,
            self.TERMS_KEY,
            json.dumps({"day": today.isoformat(), "terms": terms.to_dict()}),
        )
        return terms

    @staticmethod
    def bonus_active(session: Session, today: date) -> bool:
        """The metrics bonus applies while sharing is on and a batch was sent in the last 7 days.
        It starts the UTC day after a send, like other changes to limits."""
        if not _MetricsSettings.get_opt_in(session):
            return False
        sent = _Settings.get(session, _MetricsSettings.LAST_SENT_KEY)
        try:
            last = datetime.fromisoformat(sent).date() if sent else None
        except ValueError:
            last = None
        return (
            last is not None and last < today and (today - last).days <= _Credits.BONUS_LAPSE_DAYS
        )

    WALLET_RE = re.compile(r"^[a-z][a-z0-9-]*$")
    GITHUB_PRIVATE_KEY = "credits_github_private"
    BONUS_WALLETS = ("local", "github")  # the metrics bonus doesn't touch add-on sub-wallets

    def wallet_for(self, name: str) -> _Wallet:
        """The wallet called `name`."""
        if not isinstance(name, str) or not self.WALLET_RE.match(name):
            raise ValueError(f"{name!r} isn't a wallet name.")
        return self.wallets.setdefault(name, _Wallet(name))

    @staticmethod
    def github_private(session: Session) -> bool:
        """Whether the GitHub runner repo is private (which sets the GitHub daily amount)."""
        return _Settings.get(session, _Credits.GITHUB_PRIVATE_KEY) != "0"

    @staticmethod
    def set_github_private(session: Session, private: bool) -> None:
        _Settings.set(session, _Credits.GITHUB_PRIVATE_KEY, "1" if private else "0")

    def sync(self, session: Session, wallet: str = LOCAL) -> _Terms:
        """Bring a wallet up to now and return today's terms."""
        terms = self.terms(session)
        bonus = wallet in self.BONUS_WALLETS and self.bonus_active(session, _Clock.today(session))
        self.wallet_for(wallet).sync(session, terms, bonus, self.github_private(session))
        return terms

    def pricing(self, session: Session, wallet: str = LOCAL) -> _Pricing:
        return _Pricing(self.sync(session, wallet))

    # ----- reading ----------------------------------------------------------------------------

    def balance(self, session: Session, wallet: str = LOCAL) -> tuple[_Balance, _Terms, datetime]:
        terms = self.sync(session, wallet)
        return (
            self.wallet_for(wallet).balance(session),
            terms,
            next_midnight(_Clock.today(session)),
        )

    def today_allowance(self, session: Session, wallet: str = LOCAL) -> tuple[int, int, int]:
        """Today's baseline, bonus and promotion grants of a wallet, in milli-credits."""
        today = _Clock.today(session)
        out = []
        for ref in (f"daily:{today}", f"bonus:{today}"):
            grant = session.scalars(
                select(_CreditGrant).where(_CreditGrant.wallet == wallet, _CreditGrant.ref == ref)
            ).first()
            out.append(grant.amount_milli if grant else 0)
        promo = session.scalars(
            select(func.coalesce(func.sum(_CreditGrant.amount_milli), 0)).where(
                _CreditGrant.wallet == wallet, _CreditGrant.ref.like(f"promo:%:{today}")
            )
        ).one()
        return out[0], out[1], int(promo)

    @staticmethod
    def _moment(value: datetime | str, name: str) -> str:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                raise ValueError(f"{name} must be a datetime or an ISO 8601 string.") from None
        if not isinstance(value, datetime):
            raise TypeError(f"{name} must be a datetime or an ISO 8601 string.")
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()

    def history(
        self,
        session: Session,
        *,
        kind: CreditEntryKind | str | None = None,
        wallet: str | None = None,
        source_id: int | None = None,
        run_id: int | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        sort_by: CreditSortBy | str = CreditSortBy.AT,
        order: SortOrder | str = SortOrder.DESC,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[_CreditLedger]:
        from vethuq._sources import _Sources  # noqa: PLC0415 - avoids an import cycle

        sort = _Sources._coerce(CreditSortBy, sort_by, "sort_by")  # type: ignore[type-var]
        direction = _Sources._coerce(SortOrder, order, "order")
        statement = select(_CreditLedger)
        if kind is not None:
            wanted = _Sources._coerce(CreditEntryKind, kind, "kind")  # type: ignore[type-var]
            statement = statement.where(_CreditLedger.kind == _LedgerKind(wanted.value))
        if wallet is not None:
            statement = statement.where(_CreditLedger.wallet == wallet)
        if source_id is not None:
            statement = statement.where(_CreditLedger.source_id == source_id)
        if run_id is not None:
            statement = statement.where(_CreditLedger.run_id == run_id)
        if since is not None:
            statement = statement.where(_CreditLedger.at >= self._moment(since, "since"))
        if until is not None:
            statement = statement.where(_CreditLedger.at <= self._moment(until, "until"))
        column = getattr(_CreditLedger, sort.value)
        descending = direction is SortOrder.DESC
        statement = statement.order_by(
            column.desc() if descending else column.asc(),
            _CreditLedger.id.desc() if descending else _CreditLedger.id.asc(),
        )
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return list(session.scalars(statement))

    # ----- licence grants ---------------------------------------------------------------------

    def redeem(
        self, session: Session, grant_id: str, amount: float, scope: str | None, expires: Any
    ) -> tuple[bool, int]:
        """Add a one-off grant from a licence, once per `grant_id`. Returns (added, milli added)."""
        terms = self.sync(session)
        now = _Clock.now(session)
        if isinstance(amount, bool) or not isinstance(amount, int | float) or amount <= 0:
            raise _InvalidGrantError(f"Grant {grant_id!r} has no credits.")
        expiry = self._expiry(grant_id, expires, now, terms)
        ref = f"grant:{grant_id}"
        existing = session.scalars(
            select(_CreditGrant).where(_CreditGrant.wallet == LOCAL, _CreditGrant.ref == ref)
        ).first()
        if existing is not None:
            return False, 0
        add = milli(amount)
        if terms.one_off_max is not None:
            held = self.wallet.balance(session).one_off_milli
            room = max(milli(terms.one_off_max) - held, 0)
            if room == 0:
                raise _InvalidGrantError(
                    "You already hold the most one-off credits allowed.",
                    "Use some, then redeem again.",
                )
            add = min(add, room)
        grant = self.wallet.add_one_off(
            session, ref, add, "licence", scope=scope or None, expires=expiry
        )
        return grant is not None, add if grant is not None else 0

    @staticmethod
    def _expiry(grant_id: str, expires: Any, now: datetime, terms: _Terms) -> datetime:
        if expires in (None, ""):
            return now + timedelta(days=terms.one_off_expiry_days)
        try:
            moment = (
                expires if isinstance(expires, datetime) else datetime.fromisoformat(str(expires))
            )
        except ValueError:
            raise _InvalidGrantError(f"Grant {grant_id!r} has an invalid expiry.") from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        if moment <= now:
            raise _InvalidGrantError(f"Grant {grant_id!r} has expired.")
        return moment


class _PageMeter:
    """Charges the pages of one file as they are read, and can give it all back if the file
    fails. Each charge is committed at once, so the balance shows the latest state."""

    def __init__(
        self,
        credits: _Credits,
        *,
        source_id: int | None,
        run_id: int | None,
        label: str,
        language: str,
        additional_language: bool,
        scope: str | None = None,
        wallet: str = LOCAL,
    ) -> None:
        self.credits = credits
        self.wallet_name = wallet
        self.wallet = credits.wallet_for(wallet)
        self.source_id, self.run_id = source_id, run_id
        self.label, self.language = label, language
        self.additional_language = additional_language
        self.scope = scope
        self.ledger_ids: list[int] = []
        self.charged_milli = 0
        self._pricing: _Pricing | None = None
        self._terms: _Terms | None = None

    def pricing(self) -> _Pricing:
        if self._pricing is None:
            with self.credits.database.session() as session:
                self._terms = self.credits.sync(session, self.wallet_name)
            self._pricing = _Pricing(self._terms)
        return self._pricing

    def quote(self, width_pt, height_pt, covered: float) -> tuple[float, int]:
        """(size factor, cost in milli-credits). Raises `_PageTooLarge`."""
        pricing = self.pricing()
        factor = pricing.size_factor(width_pt, height_pt)
        cost = pricing.cost_milli(
            factor, additional_language=self.additional_language, covered=covered
        )
        return factor, cost

    def reserve(self, cost_milli: int) -> int:
        with self.credits.database.session() as session:
            self.credits.sync(session, self.wallet_name)
            return self.wallet.reserve(session, cost_milli, self.scope)

    def release(self, held: int) -> None:
        self.wallet.release(held)

    def commit(
        self, held: int, actual_milli: int, page_number: int, factor: float, phase: str
    ) -> int:
        with self.wallet.lock, self.credits.database.session() as session:
            ids = self.wallet.commit(
                session,
                held,
                actual_milli,
                self.scope,
                source_id=self.source_id,
                run_id=self.run_id,
                page_number=page_number,
                phase=phase,
                angle=0,
                language=self.language,
                size_factor_milli=milli(factor),
                rate_card_version=self._terms.rate_card_version if self._terms else None,
                note=self.label,
            )
            if self.run_id is not None and actual_milli > 0:
                run = session.get(_IndexRun, self.run_id)
                if run is not None:
                    run.credits_milli += actual_milli
                    run.ocr_pages += 1
        self.ledger_ids += ids
        self.charged_milli += actual_milli
        return actual_milli

    def refund_all(self, note: str = "the file was not indexed") -> None:
        if not self.ledger_ids:
            return
        with self.wallet.lock, self.credits.database.session() as session:
            self.wallet.refund(session, self.ledger_ids, note)
            if self.run_id is not None:
                run = session.get(_IndexRun, self.run_id)
                if run is not None:
                    run.credits_milli = max(run.credits_milli - self.charged_milli, 0)
                    run.ocr_pages = max(run.ocr_pages - len(self.ledger_ids), 0)
        self.ledger_ids, self.charged_milli = [], 0


__all__ = ["_Credits", "_PageMeter", "_PageTooLarge"]
