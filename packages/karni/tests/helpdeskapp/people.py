"""What the help desk contributes to the people contract: a fact, a merge hook, an erase hook."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from karni import people
from tests.helpdeskapp.models import SupportProfile, Ticket

people.register_fact(
    "open_tickets",
    people.count_of(Ticket, filter=Q(status="open")),
    label="Open tickets",
    kind="count",
)

PLANS = ("basic", "priority")


@people.merge_hook(SupportProfile)
def merge_profiles(keep: Any, drop: Any) -> None:
    """Both people had a profile: the kept one takes the better plan, the other goes."""
    kept = SupportProfile.objects.filter(person=keep).first()
    dropped = SupportProfile.objects.filter(person=drop).first()
    if kept is None or dropped is None:
        return
    if PLANS.index(dropped.plan) > PLANS.index(kept.plan):
        kept.plan = dropped.plan
        kept.save(update_fields=["plan"])
    dropped.delete()


people.erasable(Ticket, fields={"contact_name": "", "contact_email": ""})
