"""A wallet (local, github): the day's grants, what is left, and spending it in order."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vethuq._credits.clock import _Clock
from vethuq._credits.terms import _Terms, milli
from vethuq._db import _CreditGrant, _CreditLedger
from vethuq._db.values import _GrantKind, _LedgerKind
from vethuq._errors import _CreditsExhaustedError

LOCAL = "local"
_RANK = {_GrantKind.PROMO: 0, _GrantKind.DAILY: 1, _GrantKind.ONE_OFF: 2, _GrantKind.GRACE: 4}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def next_midnight(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)


@dataclass(frozen=True)
class _Balance:
    daily_milli: int  # today's allowance left, with any metrics bonus
    promo_milli: int
    one_off_milli: int
    grace_milli: int

    @property
    def total_milli(self) -> int:
        """Everything that can be spent, grace included."""
        return self.daily_milli + self.promo_milli + self.one_off_milli + self.grace_milli


@dataclass(frozen=True)
class _Debit:
    grant_id: int
    amount_milli: int


class _Wallet:
    """One wallet. In-flight work is held in memory (`reserve`) so workers can't spend the same
    credits twice; what is spent is written to the grants and the ledger as it happens."""

    def __init__(self, name: str = LOCAL) -> None:
        self.name = name
        self._lock = threading.RLock()
        self._held = 0

    @property
    def lock(self) -> threading.RLock:
        """Held while a charge is written and committed, so workers never read stale grants."""
        return self._lock

    # ----- grants -----------------------------------------------------------------------------

    def _add(
        self,
        session: Session,
        kind: _GrantKind,
        origin: str,
        ref: str,
        amount_milli: int,
        *,
        expires: datetime | None,
        scope: str | None = None,
        now: datetime,
    ) -> _CreditGrant | None:
        """Add a grant unless this wallet already has the `ref`. Returns it, or None if it was
        there (or empty)."""
        if amount_milli <= 0:
            return None
        exists = session.scalars(
            select(_CreditGrant.id).where(_CreditGrant.wallet == self.name, _CreditGrant.ref == ref)
        ).first()
        if exists is not None:
            return None
        grant = _CreditGrant(
            wallet=self.name,
            kind=kind,
            origin=origin,
            scope=scope,
            ref=ref,
            amount_milli=amount_milli,
            remaining_milli=amount_milli,
            granted_at=_iso(now),
            expires_at=_iso(expires) if expires else None,
        )
        try:
            with session.begin_nested():
                session.add(grant)
                session.flush()
        except IntegrityError:
            return None
        if kind is not _GrantKind.GRACE:  # the grace is only an allowance, not a grant of credits
            session.add(
                _CreditLedger(
                    at=_iso(now),
                    wallet=self.name,
                    kind=_LedgerKind.GRANT,
                    amount_milli=amount_milli,
                    grant_id=grant.id,
                    note=origin if scope is None else f"{origin} ({scope})",
                )
            )
        session.flush()
        return grant

    def add_one_off(
        self,
        session: Session,
        ref: str,
        amount_milli: int,
        origin: str,
        *,
        scope: str | None,
        expires: datetime | None,
    ) -> _CreditGrant | None:
        return self._add(
            session,
            _GrantKind.ONE_OFF,
            origin,
            ref,
            amount_milli,
            expires=expires,
            scope=scope,
            now=_Clock.now(session),
        )

    def sync(
        self, session: Session, terms: _Terms, bonus_active: bool, private: bool = True
    ) -> None:
        """Bring the wallet up to now: expire what lapsed and add today's grants (each once)."""
        with self._lock:
            now = _Clock.now(session)
            today = now.date()
            self._expire(session, now)
            if terms.starter_for(self.name) > 0:
                self._add(
                    session,
                    _GrantKind.ONE_OFF,
                    "starter",
                    "starter",
                    milli(terms.starter_for(self.name)),
                    expires=None,
                    now=now,
                )
            base = milli(terms.daily_for(self.name, private))
            end = next_midnight(today)
            borrowed = self._borrowed(session, today, terms)
            bonus = round(base * min(terms.bonus_percent, terms.bonus_cap_percent) / 100)
            bonus = bonus if bonus_active else 0
            promo = terms.best_promotion(today, base, self.name)
            promo_amount = promo[1] if promo else 0
            ceiling = milli(terms.device_daily_ceiling) if terms.device_daily_ceiling else None
            if ceiling is not None:  # a safety net: promotion first, then bonus, give way
                room = max(ceiling - base, 0)
                promo_amount = min(promo_amount, room)
                bonus = min(bonus, max(room - promo_amount, 0))
            self._add(
                session, _GrantKind.DAILY, "baseline", f"daily:{today}",
                max(base - borrowed, 0), expires=end, now=now,
            )  # fmt: skip
            self._add(
                session, _GrantKind.DAILY, "metrics_bonus", f"bonus:{today}",
                bonus, expires=end, now=now,
            )  # fmt: skip
            if promo and promo_amount:
                self._add(
                    session, _GrantKind.PROMO, f"promo:{promo[0].id}",
                    f"promo:{promo[0].id}:{today}", promo_amount, expires=end, now=now,
                )  # fmt: skip
            grace = round((base + bonus) * terms.grace_percent / 100)
            self._add(
                session, _GrantKind.GRACE, "grace", f"grace:{today}", grace, expires=end, now=now
            )

    def _borrowed(self, session: Session, today: date, terms: _Terms) -> int:
        """In `borrow` mode, the grace used yesterday comes off today's allowance."""
        if terms.grace_mode != "borrow":
            return 0
        row = session.scalars(
            select(_CreditGrant).where(
                _CreditGrant.wallet == self.name,
                _CreditGrant.ref == f"grace:{today - timedelta(days=1)}",
            )
        ).first()
        return row.amount_milli - row.remaining_milli if row else 0

    def _expire(self, session: Session, now: datetime) -> None:
        lapsed = session.scalars(
            select(_CreditGrant).where(
                _CreditGrant.wallet == self.name,
                _CreditGrant.remaining_milli > 0,
                _CreditGrant.expires_at.is_not(None),
                _CreditGrant.expires_at <= _iso(now),
            )
        ).all()
        for grant in lapsed:
            if grant.kind is not _GrantKind.GRACE:  # unused grace isn't worth a row
                session.add(
                    _CreditLedger(
                        at=_iso(now),
                        wallet=self.name,
                        kind=_LedgerKind.EXPIRE,
                        amount_milli=grant.remaining_milli,
                        grant_id=grant.id,
                        note=grant.origin,
                    )
                )
            grant.remaining_milli = 0
        session.flush()

    # ----- balance ----------------------------------------------------------------------------

    def _live(self, session: Session, now: datetime, scope: str | None):
        statement = select(_CreditGrant).where(
            _CreditGrant.wallet == self.name,
            _CreditGrant.remaining_milli > 0,
            (_CreditGrant.expires_at.is_(None)) | (_CreditGrant.expires_at > _iso(now)),
        )
        if scope is None:
            statement = statement.where(_CreditGrant.scope.is_(None))
        else:
            statement = statement.where(
                (_CreditGrant.scope.is_(None)) | (_CreditGrant.scope == scope)
            )
        return session.scalars(statement).all()

    def balance(self, session: Session, scope: str | None = None) -> _Balance:
        now = _Clock.now(session)
        sums = {kind: 0 for kind in _GrantKind}
        for grant in self._live(session, now, scope):
            sums[grant.kind] += grant.remaining_milli
        return _Balance(
            sums[_GrantKind.DAILY],
            sums[_GrantKind.PROMO],
            sums[_GrantKind.ONE_OFF],
            sums[_GrantKind.GRACE],
        )

    # ----- spending ---------------------------------------------------------------------------

    def _plan(self, session: Session, amount_milli: int, scope: str | None) -> list[_Debit] | None:
        now = _Clock.now(session)

        def order(grant: _CreditGrant):
            rank = _RANK[grant.kind]
            if grant.kind is _GrantKind.ONE_OFF and grant.scope is not None:
                rank = 2  # scoped one-off before general one-off
            elif grant.kind is _GrantKind.ONE_OFF:
                rank = 3
            return (rank, grant.expires_at is None, grant.expires_at or "", grant.id)

        left, plan = amount_milli, []
        for grant in sorted(self._live(session, now, scope), key=order):
            take = min(left, grant.remaining_milli)
            if take > 0:
                plan.append(_Debit(grant.id, take))
                left -= take
            if left == 0:
                return plan
        return None

    def reserve(self, session: Session, amount_milli: int, scope: str | None = None) -> int:
        """Hold `amount_milli` for work about to start. Raises `CreditsExhaustedError` if the
        wallet (grace included) can't cover it. Pass the result to `commit` or `release`."""
        with self._lock:
            have = self.balance(session, scope).total_milli
            if have - self._held < amount_milli:
                raise _CreditsExhaustedError(
                    "There aren't enough credits for this page.",
                    "They reset at 00:00 UTC; run again then.",
                )
            self._held += amount_milli
            return amount_milli

    def release(self, held_milli: int) -> None:
        with self._lock:
            self._held = max(self._held - held_milli, 0)

    def commit(
        self,
        session: Session,
        held_milli: int,
        actual_milli: int,
        scope: str | None = None,
        **details: object,
    ) -> list[int]:
        """Spend `actual_milli` (at most what was held), writing a ledger row per grant used.
        Returns the ledger row ids."""
        with self._lock:
            self._held = max(self._held - held_milli, 0)
            if actual_milli <= 0:
                return []
            plan = self._plan(session, actual_milli, scope)
            if plan is None:
                raise _CreditsExhaustedError("There aren't enough credits for this page.")
            now = _Clock.now(session)
            ids = []
            for debit in plan:
                # One conditional update, so two processes can never both spend the same credits.
                spent = session.execute(
                    update(_CreditGrant)
                    .where(
                        _CreditGrant.id == debit.grant_id,
                        _CreditGrant.remaining_milli >= debit.amount_milli,
                    )
                    .values(remaining_milli=_CreditGrant.remaining_milli - debit.amount_milli)
                )
                if spent.rowcount != 1:
                    raise _CreditsExhaustedError("There aren't enough credits for this page.")
                grant = session.get(_CreditGrant, debit.grant_id)
                session.refresh(grant)
                row = _CreditLedger(
                    at=_iso(now),
                    wallet=self.name,
                    kind=_LedgerKind.CHARGE,
                    amount_milli=debit.amount_milli,
                    grant_id=grant.id,
                    **details,
                )
                session.add(row)
                session.flush()
                ids.append(row.id)
            return ids

    def refund(self, session: Session, ledger_ids: list[int], note: str = "refund") -> int:
        """Give back charges (failed or interrupted work). Returns the milli-credits returned."""
        total = 0
        with self._lock:
            now = _Clock.now(session)
            for row_id in ledger_ids:
                row = session.get(_CreditLedger, row_id)
                if row is None or row.kind is not _LedgerKind.CHARGE:
                    continue
                grant = session.get(_CreditGrant, row.grant_id) if row.grant_id else None
                expired = grant is None or (grant.expires_at and grant.expires_at <= _iso(now))
                if not expired:
                    grant.remaining_milli += row.amount_milli
                session.add(
                    _CreditLedger(
                        at=_iso(now),
                        wallet=self.name,
                        kind=_LedgerKind.REFUND,
                        amount_milli=row.amount_milli if not expired else 0,
                        grant_id=row.grant_id,
                        source_id=row.source_id,
                        run_id=row.run_id,
                        page_number=row.page_number,
                        phase=row.phase,
                        note=note,
                    )
                )
                total += 0 if expired else row.amount_milli
            session.flush()
        return total

    def spent_today_milli(self, session: Session) -> int:
        today = _Clock.today(session).isoformat()
        value = session.scalar(
            select(func.coalesce(func.sum(_CreditLedger.amount_milli), 0)).where(
                _CreditLedger.wallet == self.name,
                _CreditLedger.kind == _LedgerKind.CHARGE,
                _CreditLedger.at >= today,
            )
        )
        return int(value or 0)
