"""Writing the timeline: record() by hand, entries from declared events, merge, erase, prune."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from karni import people, timeline
from karni.events import declare
from karni.exceptions import KarniError
from karni.outbox.bus import Registry, build
from karni.people.models import Person
from karni.testing import capture_events, deliver_now
from karni.timeline import subscribers
from karni.timeline.models import TimelineEntry, TimelineLink
from karni.timeline.services import parse_option, render
from tests.helpdeskapp.models import Ticket
from tests.helpdeskapp.services import close_ticket, open_ticket
from tests.loyaltyapp.services import log_visit

pytestmark = pytest.mark.django_db


def _refs(entry: TimelineEntry) -> set[str]:
    return {link.ref for link in TimelineLink.objects.filter(entry=entry)}


# record() by hand


def test_a_part_records_an_entry_by_hand(cast: dict[str, Any]) -> None:
    visit = log_visit(cast["ines"], dt.date(2026, 11, 2), Decimal("18.40"), actor=cast["agent"])
    entry = TimelineEntry.objects.get()
    assert entry.kind == "loyaltyapp.visit" and entry.source == "loyaltyapp"
    assert entry.title == "Visited the club and spent 18.40"
    assert entry.person == cast["ines"] and entry.actor == cast["agent"]
    assert entry.data == {"spent": "18.40", "visited_on": "2026-11-02"}
    assert _refs(entry) == {f"loyaltyapp.visit:{visit.pk}"}


def test_record_links_any_record_and_cuts_a_long_title(cast: dict[str, Any]) -> None:
    ticket = Ticket.objects.create(person=cast["omar"], subject="Locker")
    entry = timeline.record(
        kind="helpdeskapp.call",
        title="Called " + "back " * 100,
        subjects=[ticket, ("people.organisation", str(cast["org"].pk)), ticket],
        body="Left a message.",
    )
    assert entry is not None and entry.person is None
    assert len(entry.title) <= 300 and entry.title.endswith("...")
    assert _refs(entry) == {
        f"helpdeskapp.ticket:{ticket.pk}",
        f"people.organisation:{cast['org'].pk}",
    }


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"kind": "Call", "title": "x", "person": None}, "E462"),
        ({"kind": "crm", "title": "x"}, "E462"),
        ({"kind": "crm.call", "title": "  "}, "E462"),
        ({"kind": "crm.call", "title": "x"}, "E462"),  # neither person nor subject
        ({"kind": "crm.call", "title": "x", "subjects": [("nope.model", 1)]}, "E462"),
        ({"kind": "crm.call", "title": "x", "subjects": ("people.person", "x")}, "E462"),
        ({"kind": "crm.call", "title": "x", "person": "not-a-key"}, "E462"),
        ({"kind": "crm.call", "title": "x", "subjects": [("people.person", "x")]}, "E462"),
        (
            {
                "kind": "crm.call",
                "title": "x",
                "subjects": [("people.person", "00000000-0000-0000-0000-000000000001")],
                "event_id": "not-an-id",
            },
            "E462",
        ),
    ],
)
def test_record_refuses_what_it_cannot_use(arguments: dict[str, Any], code: str) -> None:
    with pytest.raises(KarniError) as caught:
        timeline.record(**arguments)
    assert caught.value.code == code


def test_record_refuses_a_row_that_is_not_a_person(cast: dict[str, Any]) -> None:
    with pytest.raises(KarniError) as caught:
        timeline.record(kind="crm.call", title="x", person=cast["org"])
    assert caught.value.code == "E462"
    with pytest.raises(KarniError) as caught:
        timeline.record(kind="crm.call", title="x", person=cast["ines"], data={"row": cast["org"]})
    assert caught.value.code == "E462"


def test_record_is_idempotent_per_event_and_person(cast: dict[str, Any]) -> None:
    event_id = "8a7d1c52-0b6e-4c1f-9d1e-1f2a3b4c5d6e"
    first = timeline.record(kind="crm.call", title="x", person=cast["ines"], event_id=event_id)
    again = timeline.record(kind="crm.call", title="y", person=cast["ines"], event_id=event_id)
    other = timeline.record(kind="crm.call", title="z", person=cast["omar"], event_id=event_id)
    assert first is not None and again is not None and other is not None
    assert again.pk == first.pk and other.pk != first.pk
    assert TimelineEntry.objects.count() == 2


def test_record_does_nothing_without_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.apps import apps

    real = apps.is_installed
    monkeypatch.setattr(apps, "is_installed", lambda name: name != "karni.timeline" and real(name))
    assert timeline.record(kind="crm.call", title="x", person="whoever") is None
    assert not timeline.installed()


# entries from declared events


def test_a_declared_event_lands_on_the_person_and_its_subject(cast: dict[str, Any]) -> None:
    ticket = open_ticket(cast["ines"], "Boat booking")
    assert TimelineEntry.objects.count() == 0  # nothing before the commit
    report = deliver_now()
    assert len(report.delivered) >= 1
    entry = TimelineEntry.objects.get()
    assert entry.kind == "helpdeskapp.ticket.opened" and entry.source == "helpdeskapp"
    assert entry.title == "Ticket opened: Boat booking" and entry.person == cast["ines"]
    assert entry.event_id is not None and entry.data["topic"] == "Boat booking"
    assert _refs(entry) == {f"helpdeskapp.ticket:{ticket.pk}"}

    close_ticket(ticket, minutes=42)
    deliver_now()
    closed = TimelineEntry.objects.get(kind="helpdeskapp.ticket.closed")
    assert closed.title == "Ticket closed: Boat booking"
    assert closed.body == "Closed after 42 minutes."


def test_a_redelivered_event_writes_nothing_twice(cast: dict[str, Any]) -> None:
    with capture_events() as published:
        open_ticket(cast["omar"], "Oars")
    event = published.assert_published("helpdeskapp.ticket.opened")
    deliver_now()
    declaration = build("helpdeskapp.ticket.opened", person=cast["omar"], ticket="t", topic="x")[1]
    again = timeline.write_from_event(event, declaration)
    assert again is not None and TimelineEntry.objects.count() == 1


def test_an_event_about_a_merged_person_lands_on_the_kept_one(cast: dict[str, Any]) -> None:
    drop = Person.objects.create(email="ines.d@example.com", given_name="Ines")
    with capture_events() as published:
        open_ticket(drop, "Old address")
    people.merge(cast["ines"], drop)
    deliver_now()
    entries = {e.kind: e for e in TimelineEntry.objects.all()}
    assert entries["helpdeskapp.ticket.opened"].person == cast["ines"]
    merged = entries["people.person.merged"]
    assert merged.person == cast["ines"] and merged.title == "Merged with a duplicate record"
    assert published.assert_published("helpdeskapp.ticket.opened").person == str(drop.pk)


def test_the_people_events_with_a_title_reach_the_timeline(cast: dict[str, Any]) -> None:
    from karni.people.models import Organisation

    keep = cast["org"]
    drop = Organisation.objects.create(name="Harbour Rowing")
    people.merge(keep, drop)
    deliver_now()
    entry = TimelineEntry.objects.get(kind="people.organisation.merged")
    assert entry.person is None and _refs(entry) == {f"people.organisation:{keep.pk}"}
    assert not TimelineEntry.objects.filter(kind="people.person.created").exists()


def test_an_event_without_person_or_subject_writes_nothing() -> None:
    registry = Registry()
    declaration = declare(
        "helpdeskapp.queue.emptied",
        fields={"queue": "the queue"},
        timeline="{queue} emptied",
        registry=registry,
    )
    event, _ = build("helpdeskapp.queue.emptied", actor=None, queue="front desk", registry=registry)
    assert timeline.write_from_event(event, declaration) is None


def test_every_declaration_with_a_title_has_one_subscriber() -> None:
    from karni.outbox.bus import registry

    names = {s.name for s in registry.subscribers() if s.name.startswith(subscribers.PREFIX)}
    assert "karni.timeline:helpdeskapp.ticket.opened@v1" in names
    assert "karni.timeline:people.person.merged@v1" in names
    assert "karni.timeline:people.person.created@v1" not in names
    assert subscribers.connect() == []  # already connected: nothing added


def test_subscribers_follow_a_late_declaration_and_the_switch(settings: Any) -> None:
    registry = Registry()
    declare("helpdeskapp.call.logged", fields={"who": "x"}, timeline="Call", registry=registry)
    assert subscribers.connect(registry) == ["karni.timeline:helpdeskapp.call.logged@v1"]
    assert subscribers.disconnect(registry) == ["karni.timeline:helpdeskapp.call.logged@v1"]
    settings.KARNI_TIMELINE_FROM_EVENTS = False
    assert subscribers.connect(registry) == []


# the timeline= option


@pytest.mark.parametrize(
    "option",
    [
        "Paid {amount!r}",
        "Paid {amount:>10}",
        "Paid {payment.id}",
        "Paid {missing}",
        "Paid {",
        {"title": ""},
        {"title": "x", "colour": "red"},
        {"title": "x", "subjects": {"amount": "nope.model"}},
        {"title": "x", "subjects": {"nothere": "people.person"}},
        {"title": "x", "subjects": ["amount"]},
        {"title": "x", "kind": "Bad Kind"},
        ["x"],
    ],
)
def test_a_malformed_option_is_e460(option: Any) -> None:
    registry = Registry()
    with pytest.raises(KarniError) as caught:
        declaration = declare(
            "helpdeskapp.payment.made",
            fields={"amount": "x", "payment": "y"},
            timeline=option,
            registry=registry,
        )
        parse_option(declaration)
    assert caught.value.code in {"E460", "E452"}


def test_a_template_reads_declared_fields_only_as_text() -> None:
    assert render("Paid {amount} by {who}", {"amount": "12.50", "who": None}) == "Paid 12.50 by"
    assert render("{flag} {count} {{x}}", {"flag": True, "count": 3}) == "true 3 {x}"


def test_the_checks(settings: Any) -> None:
    from karni.timeline.checks import check_timeline

    assert [m.id for m in check_timeline()] == []
    registry_declarations = Registry()
    bad = declare(
        "helpdeskapp.bad.thing", fields={"a": "x"}, timeline="{b}", registry=registry_declarations
    )
    from karni.outbox import bus

    bus.registry.add_declaration(bad)
    try:
        assert [m.id for m in check_timeline()] == ["karni.E460"]
    finally:
        bus.registry._declarations.pop("helpdeskapp.bad.thing")


def test_the_checks_without_people_or_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.apps import apps

    from karni.timeline.checks import check_timeline

    real = apps.is_installed
    monkeypatch.setattr(
        apps,
        "is_installed",
        lambda name: name not in {"karni.people", "karni.outbox"} and real(name),
    )
    assert [m.id for m in check_timeline()] == ["karni.E461", "karni.W460"]


# merge, erase, retention


def test_a_merge_moves_the_entries_and_links(cast: dict[str, Any]) -> None:
    drop = Person.objects.create(email="omar.h@example.com")
    timeline.record(kind="crm.call", title="About the drop", person=drop, subjects=[drop])
    plan = people.merge_plan(cast["omar"], drop)
    assert plan.allowed
    people.merge(cast["omar"], drop)
    entry = TimelineEntry.objects.get(kind="crm.call")
    assert entry.person == cast["omar"]
    assert _refs(entry) == {f"people.person:{cast['omar'].pk}"}


def test_erasing_a_person_deletes_their_entries(cast: dict[str, Any]) -> None:
    timeline.record(kind="crm.call", title="Called Ines", person=cast["ines"])
    timeline.record(kind="crm.note", title="Ines prefers mornings", subjects=[cast["ines"]])
    timeline.record(kind="crm.call", title="Called Omar", person=cast["omar"])
    people.erase(cast["ines"])
    assert list(TimelineEntry.objects.values_list("title", flat=True)) == ["Called Omar"]


def test_prune_keeps_entries_inside_the_window(cast: dict[str, Any], settings: Any) -> None:
    old = timezone.now() - dt.timedelta(days=400)
    timeline.record(kind="crm.call", title="Old", person=cast["ines"], occurred_at=old)
    timeline.record(kind="crm.note", title="Old note", person=cast["ines"], occurred_at=old)
    timeline.record(kind="crm.call", title="New", person=cast["ines"])
    assert timeline.prune() == 0  # retention is None: everything stays
    assert timeline.prune(365, kinds=["crm.note"]) == 1
    settings.KARNI_TIMELINE_RETENTION_DAYS = 365
    assert timeline.prune() == 1
    assert list(TimelineEntry.objects.values_list("title", flat=True)) == ["New"]
