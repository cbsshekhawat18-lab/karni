"""The visits part: its contracts, its event, its section and its connection."""

import pytest
from django.conf import settings
from karni import people, preferences
from karni.outbox.bus import registry
from karni.testing import deliver_now
from karni.timeline.models import TimelineEntry

from visits.services import log_visit


def test_the_contracts_it_requires_are_installed() -> None:
    for app in ("karni.people", "karni.outbox", "karni.timeline", "karni.preferences"):
        assert app in settings.INSTALLED_APPS


def test_its_event_is_declared() -> None:
    assert registry.declaration("visits.visit.logged", 1) is not None


@pytest.mark.django_db
def test_its_section_reads_its_default_and_a_saved_value() -> None:
    assert preferences.value("visits.greeting", "") == "Welcome back"
    preferences.save_section("visits", {"greeting": "Hello again"})
    assert preferences.value("visits.greeting", "") == "Hello again"


@pytest.mark.django_db
def test_a_logged_visit_lands_on_the_person_timeline_while_connected() -> None:
    person = people.resolve(email="ines.moreau@example.com", name="Ines Moreau")
    assert preferences.active("visits.visit_events")
    log_visit(person, "First visit")
    deliver_now()
    entry = TimelineEntry.objects.get(kind="visits.visit.logged")
    assert entry.title == "Visit logged: First visit" and entry.person == person
    with preferences.override(connections={"visits.visit_events": False}):
        log_visit(person, "Second visit")
    deliver_now()
    assert TimelineEntry.objects.filter(kind="visits.visit.logged").count() == 1
