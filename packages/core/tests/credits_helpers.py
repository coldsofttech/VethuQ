"""What tests need to look at that the public credits API keeps hidden."""

from __future__ import annotations


def grace_of(client, wallet: str = "local") -> float:
    """The internal grace allowance left in a wallet, in credits."""
    with client._db().session() as session:
        balance, _terms, _reset = client._credit_engine().balance(session, wallet)
    return balance.grace_milli / 1000
