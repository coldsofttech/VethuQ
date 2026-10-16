"""The credits service: terms for the day, the local wallet, charging pages, the ledger."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from vethuq._credits.clock import _Clock
from vethuq._credits.pricing import _PageTooLarge, _Pricing
from vethuq._credits.terms import _Terms, milli
from vethuq._credits.wallet import LOCAL, _Balance, _Wallet, next_midnight
from vethuq._db import _CreditGrant, _CreditLedger, _Database, _IndexRun
from vethuq._db.values import _GrantKind, _LedgerKind
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
        device: Callable[[], str] = lambda: "cpu",
        private: Callable[[], bool | None] = lambda: None,
    ) -> None:
        self.database = database
        self.policy = policy
        self.private = private  # whether the GitHub runner repo is private, if known
        self.device = device  # `gpu` while OCR may use the GPU, else `cpu`
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

    def github_private(self, session: Session) -> bool:
        """Whether the GitHub runner repo is private (which sets the GitHub daily amount). What
        the tier reports is remembered, so it still holds when the tier can't be reached; a
        change applies from the next UTC day, as the day's grant is already given."""
        reported = self.private()
        stored = _Settings.get(session, self.GITHUB_PRIVATE_KEY)
        if reported is not None and stored != ("1" if reported else "0"):
            self.set_github_private(session, reported)
            return reported
        return stored != "0"

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
        statement = select(_CreditLedger).where(self._not_grace(_CreditLedger))
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

    @staticmethod
    def _not_grace(ledger: type[_CreditLedger]) -> Any:
        """Keep out what the internal grace allowance paid for: it is goodwill, not credits the
        user spent or holds."""
        grace = select(_CreditGrant.id).where(_CreditGrant.kind == _GrantKind.GRACE)
        return or_(ledger.grant_id.is_(None), ledger.grant_id.not_in(grace))

    def grants(
        self,
        session: Session,
        *,
        wallet: str | None,
        kind: str | None,
        scope: str | None,
        include_expired: bool,
        limit: int | None,
        offset: int,
    ) -> list[tuple[_CreditGrant, str, bool]]:
        """Grants newest first, each with its name and whether it has lapsed."""
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        terms = self.terms(session)
        names = {p.id: p.name for p in terms.promotions}
        now = _Clock.now(session).astimezone(UTC).isoformat()
        # The grace is an internal goodwill allowance, not credits the user holds.
        statement = select(_CreditGrant).where(_CreditGrant.kind != _GrantKind.GRACE)
        if wallet is not None:
            statement = statement.where(_CreditGrant.wallet == wallet)
        if kind is not None:
            statement = statement.where(_CreditGrant.kind == _GrantKind(kind))
        if scope is not None:
            statement = statement.where(_CreditGrant.scope == scope)
        if not include_expired:
            statement = statement.where(
                (_CreditGrant.expires_at.is_(None)) | (_CreditGrant.expires_at > now)
            )
        statement = statement.order_by(_CreditGrant.granted_at.desc(), _CreditGrant.id.desc())
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        out = []
        for grant in session.scalars(statement):
            expired = grant.expires_at is not None and grant.expires_at <= now
            name = grant.origin
            if grant.kind is _GrantKind.PROMO:
                name = (
                    names.get(grant.ref.split(":")[1], grant.origin) if ":" in grant.ref else name
                )
            out.append((grant, name, expired))
        return out

    def usage(
        self,
        session: Session,
        *,
        group_by: str,
        wallet: str | None,
        source_id: int | None,
        since: str | None,
        until: str | None,
        sort_by: str,
        order: str,
        limit: int | None,
        offset: int,
    ) -> list[dict[str, Any]]:
        """What was spent (charges less refunds), grouped by day, source or file."""
        L = _CreditLedger
        net = func.sum(
            case(
                (L.kind == _LedgerKind.CHARGE, L.amount_milli),
                (L.kind == _LedgerKind.REFUND, -L.amount_milli),
                else_=0,
            )
        )
        pages = func.count(
            func.distinct(
                func.coalesce(L.document_id, 0) * 1000003
                + func.coalesce(L.page_number, 0) * 101
                + func.coalesce(L.run_id, 0)
            )
        )
        if group_by == "day":
            key = func.substr(L.at, 1, 10)
            columns = (key.label("key"),)
        elif group_by == "source":
            key = L.source_id
            columns = (key.label("key"),)
        elif group_by == "file":
            return self._usage_by_file(
                session, wallet, source_id, since, until, sort_by, order, limit, offset
            )
        else:
            raise ValueError("group_by is day, source or file.")
        statement = (
            select(*columns, net.label("milli"), pages.label("pages"), func.max(L.at).label("last"))
            .where(
                L.kind.in_([_LedgerKind.CHARGE, _LedgerKind.REFUND]),
                key.is_not(None),
                self._not_grace(L),
            )
            .group_by(key)
        )
        if wallet is not None:
            statement = statement.where(L.wallet == wallet)
        if source_id is not None:
            statement = statement.where(L.source_id == source_id)
        if since is not None:
            statement = statement.where(L.at >= since)
        if until is not None:
            statement = statement.where(L.at <= until)
        sorts = {"credits": "milli", "pages": "pages", "key": "key", "last": "last"}
        column = sorts.get(sort_by)
        if column is None:
            raise ValueError(f"Sort by {', '.join(sorts)}.")
        if order not in ("asc", "desc"):
            raise ValueError("order is asc or desc.")
        statement = statement.order_by(text(f"{column} {order}"), text("key asc"))
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return [dict(row._mapping) for row in session.execute(statement)]

    @staticmethod
    def file_of(kind: _LedgerKind, note: str | None) -> str | None:
        """The file a charge or refund was for: a charge's note is its path, a refund's is
        "<why>: <path>"."""
        if not note:
            return None
        if kind is _LedgerKind.REFUND:
            return note.split(": ", 1)[1] if ": " in note else None
        return note if kind is _LedgerKind.CHARGE else None

    def _usage_by_file(
        self, session, wallet, source_id, since, until, sort_by, order, limit, offset
    ) -> list[dict[str, Any]]:
        L = _CreditLedger
        pages = func.count(
            func.distinct(
                func.coalesce(L.page_number, 0) * 101 + func.coalesce(L.run_id, 0) * 1000003
            )
        )
        statement = (
            select(
                L.kind,
                L.note,
                func.sum(L.amount_milli).label("milli"),
                pages.label("pages"),
                func.min(L.source_id).label("source_id"),
                func.max(L.at).label("last"),
            )
            .where(
                L.kind.in_([_LedgerKind.CHARGE, _LedgerKind.REFUND]),
                L.note.is_not(None),
                self._not_grace(L),
            )
            .group_by(L.kind, L.note)
        )
        if wallet is not None:
            statement = statement.where(L.wallet == wallet)
        if source_id is not None:
            statement = statement.where(L.source_id == source_id)
        if since is not None:
            statement = statement.where(L.at >= since)
        if until is not None:
            statement = statement.where(L.at <= until)
        files: dict[str, dict[str, Any]] = {}
        for kind, note, milli_, count, src, last in session.execute(statement):
            path = self.file_of(kind, note)
            if path is None:
                continue
            row = files.setdefault(
                path, {"key": path, "milli": 0, "pages": 0, "source_id": src, "last": last}
            )
            if kind is _LedgerKind.CHARGE:
                row["milli"] += int(milli_ or 0)
                row["pages"] += int(count)
            else:
                row["milli"] -= int(milli_ or 0)
            row["last"] = max(row["last"] or "", last or "")
        sorts = {"credits": "milli", "pages": "pages", "key": "key", "last": "last"}
        column = sorts.get(sort_by)
        if column is None:
            raise ValueError(f"Sort by {', '.join(sorts)}.")
        if order not in ("asc", "desc"):
            raise ValueError("order is asc or desc.")
        rows = sorted(files.values(), key=lambda r: (r[column], r["key"]), reverse=order == "desc")
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        rows = rows[offset:]
        return rows if limit is None else rows[:limit]

    def refund(
        self,
        session: Session,
        wallet: str,
        ledger_ids: list[int],
        *,
        run_id: int | None,
        credits_milli: int,
        images: int,
        note: str,
    ) -> None:
        """Give back charges made earlier (work that never came back), and take them off the
        run's counters."""
        w = self.wallet_for(wallet)
        with w.lock:
            w.refund(session, ledger_ids, note)
            if run_id is not None:
                run = session.get(_IndexRun, run_id)
                if run is not None:
                    run.credits_milli = max(run.credits_milli - credits_milli, 0)
                    run.ocr_pages = max(run.ocr_pages - images, 0)

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
        # A grant scoped to an add-on that has a sub-wallet (`semantic`) tops that wallet up: the
        # add-on's credits are its own, and a scope on the local wallet could only be spent on OCR.
        sub_wallet = scope if scope and scope in terms.addon_wallets else None
        wallet = self.wallet_for(sub_wallet) if sub_wallet is not None else self.wallet
        existing = session.scalars(
            select(_CreditGrant).where(_CreditGrant.wallet == wallet.name, _CreditGrant.ref == ref)
        ).first()
        if existing is not None:
            return False, 0
        add = milli(amount)
        if terms.one_off_max is not None:
            held = wallet.balance(session).one_off_milli
            room = max(milli(terms.one_off_max) - held, 0)
            if room == 0:
                raise _InvalidGrantError(
                    "You already hold the most one-off credits allowed.",
                    "Use some, then redeem again.",
                )
            add = min(add, room)
        grant = wallet.add_one_off(
            session,
            ref,
            add,
            "licence",
            scope=None if sub_wallet is not None else (scope or None),
            expires=expiry,
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
        # Remote tiers run on CPU only; the local one on the device the OCR engine is set to use.
        self.device = credits.device() if wallet == LOCAL else "cpu"
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
            factor,
            additional_language=self.additional_language,
            covered=covered,
            device=self.device,
        )
        return factor, cost

    def reserve(self, cost_milli: int) -> int:
        with self.credits.database.session() as session:
            self.credits.sync(session, self.wallet_name)
            return self.wallet.reserve(session, cost_milli, self.scope)

    def release(self, held: int) -> None:
        self.wallet.release(held)

    def quote_rotated(self, width_pt, height_pt, covered: float, passes: int) -> tuple[float, int]:
        """(size factor, cost in milli-credits) of `passes` rotated reads of a page, as the deeper
        phases do. Raises `_PageTooLarge`."""
        pricing = self.pricing()
        factor = pricing.size_factor(width_pt, height_pt)
        return factor, pricing.rotated_milli(factor, passes, covered=covered, device=self.device)

    def commit(
        self,
        held: int,
        actual_milli: int,
        page_number: int,
        factor: float,
        phase: str,
        angle: int = 0,
        count_page: bool = True,
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
                angle=angle,
                language=self.language,
                device=self.device,
                size_factor_milli=milli(factor),
                rate_card_version=self._terms.rate_card_version if self._terms else None,
                note=self.label,
            )
            if self.run_id is not None and actual_milli > 0:
                run = session.get(_IndexRun, self.run_id)
                if run is not None:
                    run.credits_milli += actual_milli
                    run.ocr_pages += 1 if count_page else 0
        self.ledger_ids += ids
        self.charged_milli += actual_milli
        return actual_milli

    def forget(self) -> None:
        """The pages charged so far are saved: they are no longer refundable with the file."""
        self.ledger_ids, self.charged_milli = [], 0

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
