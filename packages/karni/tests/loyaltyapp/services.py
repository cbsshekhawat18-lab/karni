"""The loyalty part's services: a visit is written on the person's timeline by hand."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.db import transaction

from karni import timeline
from tests.loyaltyapp.models import Visit


def log_visit(person: Any, visited_on: dt.date, spent: Decimal, *, actor: Any = None) -> Visit:
    """Record a visit and put it on the person's timeline (nothing when there is no timeline)."""
    with transaction.atomic():
        visit = Visit.objects.create(person=person, visited_on=visited_on, spent=spent)
        timeline.record(
            kind="loyaltyapp.visit",
            title=f"Visited the club and spent {spent}",
            person=person,
            subjects=[visit],
            actor=actor,
            data={"spent": spent, "visited_on": visited_on},
        )
    return visit
