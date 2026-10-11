"""An add-on's credits: its sub-wallet, as the `Credits` an add-on's host gives it."""

from __future__ import annotations

from collections.abc import Callable

from vethuq._credits.service import _Credits
from vethuq._errors import _CreditsExhaustedError
from vethuq_addon_api import CreditsExhaustedError


class _AddonCredits:
    """The `Credits` of one add-on. The wallet is named after the add-on, so what it holds can only
    be spent on that add-on's work; the day's allowance, the one-off credits from its licence and
    the grace work as they do for any wallet."""

    def __init__(self, addon_id: str, service: Callable[[], _Credits]) -> None:
        self._wallet = addon_id
        self._service = service

    def rate(self, key: str, default: float) -> float:
        service = self._service()
        with service.database.session() as session:
            terms = service.sync(session, self._wallet)
        return terms.rate_for(key, default)

    def balance_milli(self) -> int:
        service = self._service()
        with service.database.session() as session:
            balance, _terms, _reset = service.balance(session, self._wallet)
        return balance.total_milli

    def charge(self, amount_milli: int, *, note: str = "") -> None:
        if isinstance(amount_milli, bool) or not isinstance(amount_milli, int) or amount_milli < 0:
            raise ValueError("A charge is a whole number of milli-credits, 0 or more.")
        if amount_milli == 0:
            return
        service = self._service()
        wallet = service.wallet_for(self._wallet)
        try:
            with wallet.lock, service.database.session() as session:
                terms = service.sync(session, self._wallet)
                held = wallet.reserve(session, amount_milli)
                try:
                    wallet.commit(
                        session,
                        held,
                        amount_milli,
                        None,
                        phase=self._wallet,
                        rate_card_version=terms.rate_card_version,
                        note=note,
                    )
                except BaseException:
                    wallet.release(held)
                    raise
        except _CreditsExhaustedError as error:
            raise CreditsExhaustedError(error.message, error.hint or "") from None
