"""The contracts the visits part requires are installed, and its event is declared."""

import pytest
from django.conf import settings
from karni import people
from karni.events import publish
from karni.outbox.bus import registry
from karni.testing import deliver_now
from karni.timeline.models import TimelineEntry

from visits.models import Visit


def test_the_contracts_it_requires_are_installed() -> None:
    assert "karni.people" in settings.INSTALLED_APPS
    assert "karni.outbox" in settings.INSTALLED_APPS
    assert "karni.timeline" in settings.INSTALLED_APPS


def test_its_event_is_declared() -> None:
    assert registry.declaration("visits.visit.logged", 1) is not None


@pytest.mark.django_db
def test_a_logged_visit_lands_on_the_person_timeline() -> None:
    person = people.resolve(email="ines.moreau@example.com", name="Ines Moreau")
    visit = Visit.objects.create(person=person, note="First visit")
    publish(
        "visits.visit.logged",
        subject=visit,
        person=person,
        visit=str(visit.pk),
        note=visit.note,
    )
    deliver_now()
    entry = TimelineEntry.objects.get(kind="visits.visit.logged")
    assert entry.title == "Visit logged: First visit"
    assert entry.person == person
