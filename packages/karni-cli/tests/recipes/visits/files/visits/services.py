"""Logging a visit: the row, and its family event while visits.visit_events is on."""

from django.db import transaction
from karni import preferences
from karni.events import publish

from visits.models import Visit


def log_visit(person: object, note: str) -> Visit:
    with transaction.atomic():
        visit = Visit.objects.create(person=person, note=note)
        if preferences.active("visits.visit_events"):
            publish(
                "visits.visit.logged",
                subject=visit,
                person=person,
                visit=str(visit.pk),
                note=note,
            )
    return visit
