"""What the loyalty part contributes to the people contract: facts, a merge hook, an erase hook."""

from __future__ import annotations

from typing import Any

from karni import people
from tests.loyaltyapp.models import LoyaltyCard, Visit

people.register_fact("visits", people.count_of(Visit), label="Visits", kind="count")
people.register_fact(
    "loyalty_spent", people.sum_of(Visit, "spent"), label="Spent at the club", kind="money"
)
people.register_fact(
    "last_visit", people.latest_of(Visit, "visited_on"), label="Last visit", kind="date"
)


@people.merge_hook(LoyaltyCard)
def merge_cards(keep: Any, drop: Any) -> None:
    """Both people had a card: the kept card gets the points of both, the other goes."""
    kept = LoyaltyCard.objects.filter(person=keep).first()
    dropped = LoyaltyCard.objects.filter(person=drop).first()
    if kept is None or dropped is None:
        return
    kept.points += dropped.points
    kept.nickname = kept.nickname or dropped.nickname
    kept.save(update_fields=["points", "nickname"])
    dropped.delete()


@people.erase_hook("loyaltyapp.card")
def erase_card(person: Any) -> None:
    """An erased person's card keeps its points and loses its nickname."""
    LoyaltyCard._base_manager.filter(person=person).update(nickname="")
