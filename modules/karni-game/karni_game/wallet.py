"""Experimental. Soft currencies: a balance per player and currency, and a ledger of every change.

:func:`change` is the one way a balance moves. In one transaction it locks
the wallet's row, refuses to go below 0 (``409 GAME016``), credits up to the
currency's cap and no further, writes the new balance with a conditional
``UPDATE`` (so two requests at once can never both spend the same coins),
and writes a :class:`~karni_game.models.LedgerEntry` with the amount that
moved, the balance after it and the reason.

Nothing a client sends is an amount: rewards, prices and match results are
declared on the server, and the services call :func:`change` with them.

Override / escape hatch: call :func:`change` from your own code with a
``reason`` of :data:`karni_game.models.LEDGER_REASONS`; read the ledger with
:class:`~karni_game.models.LedgerEntry` in reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, router, transaction
from django.db.models import F

from karni_game.errors import game_error
from karni_game.models import Currency, LedgerEntry, Player, Wallet

__all__ = ["Change", "balance_data", "balances", "change", "find_currency", "wallet_of"]


def find_currency(game: Any, key: str) -> Currency:
    """The game's currency ``key`` (400 when there is none)."""
    found = Currency.objects.filter(game=game, key=key).first()
    if found is None:
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"currency": [f"{game.slug} has no currency {key!r}."]})
    return found


def wallet_of(player: Player, currency: Currency) -> Wallet:
    """The player's wallet in ``currency``, made at 0 when it has none."""
    found = Wallet.objects.filter(player=player, currency=currency).first()
    if found is not None:
        return found
    try:
        with transaction.atomic(using=router.db_for_write(Wallet)):
            return Wallet.objects.create(player=player, currency=currency, balance=0)
    except IntegrityError:  # another request made it first
        return Wallet.objects.get(player=player, currency=currency)


@dataclass(frozen=True)
class Change:
    """What :func:`change` did: the entry, what moved, whether the cap took some, the balance."""

    entry: LedgerEntry | None
    amount: int
    capped: bool
    balance: int
    currency: Currency

    def as_dict(self) -> dict[str, Any]:
        return {"currency": self.currency.key, "amount": self.amount, "balance": self.balance}


def change(
    player: Player,
    currency: Currency,
    amount: int,
    *,
    reason: str,
    reference: str = "",
    intent: str = "",
    actor: Any = None,
    note: str = "",
) -> Change:
    """Move the player's balance by ``amount`` (negative spends), atomically and capped."""
    wallet = wallet_of(player, currency)
    using = router.db_for_write(Wallet)
    with transaction.atomic(using=using):
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
        before = locked.balance
        applied = amount
        if amount < 0 and before + amount < 0:
            raise game_error(
                "GAME016",
                f"The player has {before} {currency.key}, and this needs {-amount}.",
                status=409,
                balance=before,
                needed=-amount,
            )
        if amount > 0 and currency.cap is not None:
            applied = max(0, min(amount, currency.cap - before))
        # The row is locked: the conditional update is the second guard (a database
        # that does not lock rows, a balance changed by hand meanwhile).
        moved = Wallet.objects.filter(pk=locked.pk, balance=before).update(
            balance=F("balance") + applied
        )
        if not moved:  # pragma: no cover - only without row locks
            raise game_error("GAME016", "The balance changed meanwhile. Try again.", status=409)
        after = before + applied
        entry = None
        if applied:
            entry = LedgerEntry.objects.create(
                wallet=locked,
                amount=applied,
                balance_after=after,
                reason=reason,
                reference=reference[:64],
                intent=intent[:64],
                actor=actor if getattr(actor, "is_authenticated", False) else None,
                note=note[:200],
            )
    return Change(
        entry=entry,
        amount=applied,
        capped=applied < amount,
        balance=after,
        currency=currency,
    )


def balance_data(wallet: Wallet) -> dict[str, Any]:
    currency = wallet.currency
    return {
        "currency": currency.key,
        "title": currency.title,
        "balance": wallet.balance,
        "cap": currency.cap,
    }


def balances(player: Player, game: Any) -> list[dict[str, Any]]:
    """The player's balance in every currency of the game (0 where it has no wallet)."""
    held = {
        wallet.currency_id: wallet
        for wallet in Wallet.objects.filter(player=player, currency__game=game).select_related(
            "currency"
        )
    }
    rows = []
    for currency in Currency.objects.filter(game=game):
        found = held.get(currency.pk) or Wallet(player=player, currency=currency, balance=0)
        rows.append(balance_data(found))
    return rows
