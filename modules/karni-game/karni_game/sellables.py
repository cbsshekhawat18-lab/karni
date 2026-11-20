"""Experimental. Real-money items through the cart of karni-commerce: the kind ``game_item``.

karni-commerce imports this module at startup when it is installed
(``<app>/sellables.py``), and never otherwise, so karni-game does not need
commerce. An :class:`~karni_game.models.Item` with ``real_money`` and a
``money_price`` goes in the cart as ``{"kind": "game_item", "item": <its id>}``.
The buyer must be signed in: the item is the player of the order's person
once the order is paid, and goes back when it is refunded or cancelled.

Override / escape hatch: ``KARNI_COMMERCE_SELLABLES = {"game_item":
"myapp.sellables.MyItems"}`` replaces this adapter (subclass
:class:`GameItemSellable`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import models
from karni_commerce.sellables import Price, Sellable, refuse, register

from karni_game import players, shop
from karni_game.models import Item, Ownership

__all__ = ["GameItemSellable"]


@register
class GameItemSellable(Sellable):
    """A game's real-money item: one per buyer, given to their player when paid."""

    kind = "game_item"
    model = Item
    label = "Game item"
    search_fields = ("title", "key")

    def queryset(self) -> models.QuerySet[Any]:
        return Item.objects.filter(real_money=True, is_active=True).select_related("game")

    def name(self, item: Any, options: Mapping[str, Any]) -> str:
        return f"{item.title} ({item.game.title})"

    def sku(self, item: Any, options: Mapping[str, Any]) -> str:
        return f"{item.game.slug}:{item.key}"

    def price(self, item: Any, options: Mapping[str, Any], buyer: Any) -> Price:
        return Price(unit=item.money_price)

    def validate(self, item: Any, quantity: int, options: Mapping[str, Any], buyer: Any) -> None:
        if not item.real_money or item.money_price is None:
            raise refuse(f"{item.title} is not sold for money.")
        if quantity != 1:
            raise refuse(f"{item.title} is bought once.", field="quantity")
        if buyer is None or not getattr(buyer, "is_authenticated", False):
            raise refuse(f"Sign in to buy {item.title}: it goes to your player.")
        owner = Ownership.objects.filter(
            item=item, player__person__user=buyer, deleted_at__isnull=True
        )
        if owner.exists():
            raise refuse(f"You own {item.title} already.")
        super().validate(item, quantity, options, buyer)

    def _player_of(self, line: Any) -> Any:
        person = line.order.person
        return players.player_for_person(person) if person is not None else None

    def on_paid(self, line: Any) -> None:
        item = Item.objects.filter(pk=line.item).first()
        player = self._player_of(line)
        if item is None or player is None:
            return
        if not Ownership.objects.filter(player=player, item=item).exists():
            shop.give(player, item, source="order")

    def on_cancelled(self, line: Any) -> None:
        self._take(line)

    def on_refunded(self, line: Any, quantity: int, restock: bool) -> None:
        self._take(line)

    def _take(self, line: Any) -> None:
        item = Item.objects.filter(pk=line.item).first()
        player = self._player_of(line)
        if item is not None and player is not None:
            shop.take(player, item)
