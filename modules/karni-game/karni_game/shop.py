"""Cosmetics: the shop, the items a player owns, what each slot has equipped.

:func:`buy` spends the item's price from the player's wallet and gives the
item, in one transaction: a player never pays without getting it, nor gets
it without paying. An item is owned once (``GAME022``). A real-money item is
not sold for currency (``GAME031``): it goes through the cart of
karni-commerce (:mod:`karni_game.sellables`, the kind ``game_item``), and
:func:`give` hands it over once the order is paid.

Override / escape hatch: :func:`give` and :func:`take` from your own code (a
bundle, a promotion); a price is the item's row, never a client's number.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, router, transaction
from karni.events import publish

from karni_game import wallet
from karni_game.errors import game_error
from karni_game.models import Game, Item, Ownership, Player

__all__ = ["buy", "equip", "find_item", "give", "item_data", "owned", "take", "unequip"]


def find_item(game: Game, key: str) -> Item:
    found = (
        Item.objects.select_related("currency").filter(game=game, key=key, is_active=True).first()
    )
    if found is None:
        raise game_error("GAME021", f"{game.slug} has no item {key!r} in its shop.", status=404)
    return found


def owned(player: Player, game: Game) -> dict[str, Ownership]:
    """The player's items in the game, by item key."""
    rows = Ownership.objects.filter(player=player, item__game=game).select_related("item")
    return {row.item.key: row for row in rows}


def item_data(item: Item, mine: Ownership | None) -> dict[str, Any]:
    price = None
    if item.for_sale and item.currency is not None:
        price = {"currency": item.currency.key, "amount": item.price}
    return {
        "key": item.key,
        "title": item.title,
        "slot": item.slot,
        "price": price,
        "real_money": item.real_money,
        "owned": mine is not None,
        "equipped": bool(mine and mine.equipped),
    }


def give(player: Player, item: Item, *, source: str) -> Ownership:
    """Give the item (``GAME022`` when the player owns it)."""
    try:
        with transaction.atomic(using=router.db_for_write(Ownership)):
            return Ownership.objects.create(player=player, item=item, slot=item.slot, source=source)
    except IntegrityError as exc:
        raise game_error("GAME022", f"The player owns {item.key} already.", status=409) from exc


def take(player: Player, item: Item) -> bool:
    """Take the item back (a refund). ``False`` when the player did not own it."""
    found = Ownership.objects.filter(player=player, item=item).first()
    if found is None:
        return False
    found.equipped = False
    found.save(update_fields=["equipped", "updated_at"])
    found.delete()
    return True


def buy(player: Player, item: Item) -> dict[str, Any]:
    """Spend the price, give the item. ``GAME031``, ``GAME021``, ``GAME022``, ``GAME016``."""
    if item.real_money:
        raise game_error(
            "GAME031",
            f"{item.key} is sold for real money, through the cart (kind game_item), not for "
            "a currency.",
        )
    if not item.for_sale or item.currency is None or item.price is None:
        raise game_error("GAME021", f"{item.key} is not for sale.", status=404)
    if Ownership.objects.filter(player=player, item=item).exists():
        raise game_error("GAME022", f"The player owns {item.key} already.", status=409)
    with transaction.atomic(using=router.db_for_write(Ownership)):
        spent = wallet.change(
            player, item.currency, -int(item.price), reason="purchase", reference=item.key
        )
        mine = give(player, item, source="purchase")
        publish(
            "game.item.bought",
            subject=mine,
            person=player.person_id,
            game=item.game.slug,
            player=str(player.pk),
            item=item.key,
            currency=item.currency.key,
            price=int(item.price),
        )
    return {
        "item": {"key": item.key, "slot": item.slot, "equipped": False},
        "balance": {"currency": item.currency.key, "balance": spent.balance},
    }


def _mine(player: Player, item: Item) -> Ownership:
    found = Ownership.objects.filter(player=player, item=item).first()
    if found is None:
        raise game_error("GAME023", f"The player does not own {item.key}.", status=409)
    return found


def equip(player: Player, item: Item) -> dict[str, Any]:
    """Wear the item: the item that was in its slot comes off."""
    with transaction.atomic(using=router.db_for_write(Ownership)):
        mine = _mine(player, item)
        Ownership.objects.filter(player=player, slot=item.slot, equipped=True).exclude(
            pk=mine.pk
        ).update(equipped=False)
        if not mine.equipped:
            mine.equipped = True
            mine.save(update_fields=["equipped", "updated_at"])
    return {"item": item.key, "slot": item.slot, "equipped": True}


def unequip(player: Player, item: Item) -> dict[str, Any]:
    mine = _mine(player, item)
    if mine.equipped:
        mine.equipped = False
        mine.save(update_fields=["equipped", "updated_at"])
    return {"item": item.key, "slot": item.slot, "equipped": False}
