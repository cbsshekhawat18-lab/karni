"""Family events with an outbox: declare, publish, subscribe, deliver, retry, sweep, prune.

The publisher is ``tests.deskapp`` (a help desk closing tickets). The
subscriber is ``tests.notesapp``, which never imports the desk: it names
``desk.ticket.closed`` as a string. Its ``behaviour["fail"]`` makes the next
deliveries raise. Every test here runs on SQLite and on PostgreSQL
(``--ds=karni_postgres_settings``).
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest
from celery import Celery
from celery import _state as celery_state
from django.contrib.auth import get_user_model
from django.core import checks
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

from karni import events as karni_events
from karni.celery import create_celery_app
from karni.errorcodes import KarniError
from karni.events import Event, Registry, Subscriber, declare, once, publish, subscribe
from karni.middleware import current_user
from karni.outbox import delivery
from karni.outbox.bus import build
from karni.outbox.checks import check_event_bus, event_listing
from karni.outbox.delivery import backoff, deliver_event, prune, sweep
from karni.outbox.health import check_outbox
from karni.outbox.models import Delivery, Handled, OutboxEvent
from karni.testing import assert_events_declared, capture_events, deliver_now
from karni.tracing import bound_request_id
from tests.deskapp.models import Ticket
from tests.deskapp.services import close
from tests.notesapp import listeners
from tests.notesapp.models import Note, Tally

CaptureCallbacks = Callable[..., AbstractContextManager[list[Callable[[], Any]]]]

WRITE_NOTE = "tests.notesapp.listeners.write_note"
TALLY = "notes.tally_closures"


@pytest.fixture(autouse=True)
def _bus_only() -> Iterator[None]:
    """These tests count the bus's own subscribers: the timeline's are left out (tests/timeline)."""
    from karni.timeline import subscribers

    subscribers.disconnect()
    yield
    subscribers.connect()


@pytest.fixture(autouse=True)
def _notes_behave() -> Iterator[None]:
    listeners.behaviour["fail"] = 0
    listeners.never.clear()
    yield
    listeners.behaviour["fail"] = 0
    listeners.never.clear()


@pytest.fixture
def eager() -> Iterator[Celery]:
    """A factory-built Celery app, eager per tests/settings.py, as the current app."""
    previous = celery_state.get_current_app()
    app = create_celery_app("karni-family-events-tests")
    app.set_current()
    assert app.conf.task_always_eager is True
    yield app
    previous.set_current()


@pytest.fixture
def ticket(db: None) -> Ticket:
    return Ticket.objects.create(title="The printer jams", requester="person-1")


def _code(exc: pytest.ExceptionInfo[BaseException]) -> str:
    assert isinstance(exc.value, KarniError)
    return exc.value.code


# the API keeps every earlier name of karni.events


def test_karni_events_keeps_its_listener_names_and_adds_the_bus() -> None:
    kept = ("on_created", "on_updated", "on_deleted", "on_restored", "on_transition", "queued")
    for name in (*kept, "QueuedListener", "autodiscover", "is_soft_delete", "is_restore"):
        assert callable(getattr(karni_events, name))
        assert name in karni_events.__all__
    for name in ("declare", "publish", "subscribe", "once", "Event", "CONTRACT"):
        assert name in karni_events.__all__
    assert karni_events.CONTRACT == 1


# declarations


def test_the_desk_declares_its_event_at_startup() -> None:
    declaration = karni_events.declare.__globals__["registry"].declaration("desk.ticket.closed")
    assert declaration is not None
    assert declaration.version == 1
    assert list(declaration.fields) == ["ticket", "minutes"]
    assert declaration.person == "person"
    assert declaration.source == "tests.deskapp.events"
    assert declaration.prefix == "desk"


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"name": "Desk.Ticket.Closed"}, "not an event name"),
        ({"name": "desk.closed"}, "not an event name"),
        ({"name": "desk.ticket.closed", "version": 0}, "whole number from 1"),
        ({"name": "desk.ticket.closed", "version": True}, "whole number from 1"),
        ({"name": "desk.ticket.closed", "fields": {"subject": "x"}}, "already carries"),
        ({"name": "desk.ticket.closed", "fields": {"Total": "x"}}, "lower case"),
        ({"name": "desk.ticket.closed", "fields": "ticket"}, "takes fields as"),
        ({"name": "desk.ticket.closed", "fields": {"ticket": 3}}, "write a sentence"),
        ({"name": "desk.ticket.closed", "person": "owner"}, "neither"),
        ({"name": "desk.ticket.closed", "timeline": 3}, "title template"),
    ],
)
def test_a_malformed_declaration_is_refused(kwargs: dict[str, Any], words: str) -> None:
    with pytest.raises(KarniError) as exc:
        declare(**kwargs, registry=Registry())
    assert _code(exc) == "E452"
    assert words in str(exc.value)


def test_one_part_owns_an_event_and_a_module_may_declare_again() -> None:
    registry = Registry()
    first = declare("desk.ticket.closed", fields=["ticket"], registry=registry)
    again = declare("desk.ticket.closed", fields=["ticket", "minutes"], registry=registry)
    assert registry.declaration("desk.ticket.closed") == again != first
    stranger = first.__class__(**{**first.__dict__, "source": "elsewhere.events"})
    with pytest.raises(KarniError) as exc:
        registry.add_declaration(stranger)
    assert _code(exc) == "E452"
    declare("desk.ticket.closed", version=2, fields=["ticket"], registry=registry)
    assert registry.versions("desk.ticket.closed") == [1, 2]
    assert registry.declaration("desk.ticket.closed").version == 2  # type: ignore[union-attr]


# subscribers


def test_a_subscriber_needs_a_stable_unique_name() -> None:
    registry = Registry()

    def nested(event: Event) -> None: ...

    with pytest.raises(KarniError) as exc:
        subscribe("desk.ticket.closed", registry=registry)(nested)
    assert _code(exc) == "E454"
    subscribe("desk.ticket.closed", name="desk.thanks", registry=registry)(nested)
    assert registry.subscriber("desk.thanks") is not None
    other = Subscriber(
        event="desk.ticket.closed", version=1, name="desk.thanks", func=nested, source="x.y"
    )
    with pytest.raises(KarniError) as exc:
        registry.add_subscriber(other)
    assert _code(exc) == "E454"
    with pytest.raises(KarniError) as exc:
        subscribe("not a name", registry=registry)
    assert _code(exc) == "E454"
    with pytest.raises(KarniError) as exc:
        not_callable: Any = "not callable"
        subscribe("desk.ticket.closed", registry=registry)(not_callable)
    assert _code(exc) == "E454"


def test_a_subscriber_to_an_event_nothing_declares_is_never_called_and_fails_nothing(
    ticket: Ticket, eager: Celery
) -> None:
    close(ticket, minutes=3)
    deliver_now()
    assert listeners.never == []
    assert not [m for m in check_event_bus() if m.level >= checks.ERROR]
    assert (
        "absent.thing.happened v1 is not declared here (its publisher is not installed): "
        "tests.notesapp.listeners.never_called"
    ) in event_listing()


# publishing


def test_publish_writes_the_event_and_one_delivery_per_subscriber(ticket: Ticket) -> None:
    with capture_events() as published, current_user(None):
        close(ticket, minutes=12)
    event = published.assert_published(
        "desk.ticket.closed", subject=ticket, person="person-1", minutes=12
    )
    row = OutboxEvent.objects.get()
    assert str(row.pk) == event.id
    assert row.payload == event.payload
    assert row.payload["subject"] == {"model": "deskapp.ticket", "id": str(ticket.pk)}
    assert row.payload["ticket"] == str(ticket.pk)
    assert (row.subject_model, row.subject_id, row.person_id) == (
        "deskapp.ticket",
        str(ticket.pk),
        "person-1",
    )
    assert sorted(Delivery.objects.values_list("subscriber", "status")) == [
        (TALLY, "pending"),
        (WRITE_NOTE, "pending"),
    ]


def test_the_payload_carries_the_common_fields(ticket: Ticket) -> None:
    user = get_user_model().objects.create_user(email="staff@example.com", password="pw")
    with bound_request_id("req-common-1"), current_user(user):
        event = publish(
            "desk.ticket.closed", subject=ticket, person="person-1", ticket="t", minutes=1
        )
    payload = event.payload
    assert list(payload)[:8] == [
        "id",
        "name",
        "version",
        "occurred_at",
        "actor",
        "person",
        "subject",
        "request_id",
    ]
    assert uuid.UUID(payload["id"])
    assert (payload["name"], payload["version"], payload["actor"]) == (
        "desk.ticket.closed",
        1,
        str(user.pk),
    )
    assert payload["request_id"] == "req-common-1"
    assert dt.datetime.fromisoformat(payload["occurred_at"]) <= timezone.now()
    assert Event.from_payload(payload) == event


def test_values_are_written_as_json_and_instances_are_refused(ticket: Ticket) -> None:
    registry = Registry()
    declare("desk.invoice.sent", fields=["total", "ref", "due", "lines"], registry=registry)
    event, _ = build(
        "desk.invoice.sent",
        registry=registry,
        actor=None,
        total=decimal.Decimal("12.50"),
        ref=uuid.UUID(int=7),
        due=dt.date(2026, 11, 30),
        lines=[{"amount": decimal.Decimal("1.10")}],
    )
    assert event.data == {
        "total": "12.50",
        "ref": str(uuid.UUID(int=7)),
        "due": "2026-11-30",
        "lines": [{"amount": "1.10"}],
    }
    with pytest.raises(KarniError) as exc:
        build("desk.invoice.sent", registry=registry, total=ticket, ref=1, due=1, lines=[])
    assert _code(exc) == "E453"
    assert "pass its id" in str(exc.value)
    with pytest.raises(KarniError) as exc:
        build("desk.invoice.sent", registry=registry, total=object(), ref=1, due=1, lines=[])
    assert _code(exc) == "E453"


def test_publish_refuses_what_the_declaration_does_not_say(ticket: Ticket) -> None:
    with pytest.raises(KarniError) as exc:
        publish("desk.ticket.reopened", ticket="1")
    assert _code(exc) == "E450"
    with pytest.raises(KarniError) as exc:
        publish("desk.ticket.closed", version=2, person="p", ticket="1", minutes=1)
    assert _code(exc) == "E450"
    assert "declared with version 1 only" in str(exc.value)
    with pytest.raises(KarniError) as exc:
        publish("desk.ticket.closed", person="p", ticket="1")
    assert _code(exc) == "E453"
    assert "missing minutes" in str(exc.value)
    with pytest.raises(KarniError) as exc:
        publish("desk.ticket.closed", person="p", ticket="1", minutes=1, staff="x")
    assert _code(exc) == "E453"
    assert "not declared: staff" in str(exc.value)
    with pytest.raises(KarniError) as exc:
        publish("desk.ticket.closed", ticket="1", minutes=1)
    assert _code(exc) == "E453"
    assert "names no person" in str(exc.value)
    assert not OutboxEvent.objects.exists()


def test_the_person_may_come_from_a_declared_field(db: None) -> None:
    registry = Registry()
    declare("desk.person.merged", fields=["kept", "removed"], person="kept", registry=registry)
    event, _ = build("desk.person.merged", registry=registry, kept="p-1", removed="p-2")
    assert event.person == "p-1"


def test_a_rolled_back_transaction_publishes_nothing(
    ticket: Ticket, django_capture_on_commit_callbacks: CaptureCallbacks
) -> None:
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            close(ticket, minutes=1)
            raise RuntimeError("the save that follows fails")
    assert not OutboxEvent.objects.exists()
    assert not Delivery.objects.exists()
    assert callbacks == []


def test_an_event_without_subscribers_is_recorded_and_sends_nothing(
    db: None, django_capture_on_commit_callbacks: CaptureCallbacks
) -> None:
    registry = Registry()
    declare("desk.queue.emptied", fields=[], registry=registry)
    with django_capture_on_commit_callbacks() as callbacks:
        publish("desk.queue.emptied", registry=registry)
    assert OutboxEvent.objects.filter(name="desk.queue.emptied").exists()
    assert not Delivery.objects.exists()
    assert callbacks == []


def test_publishing_costs_two_queries_whatever_the_number_of_subscribers(
    ticket: Ticket, django_assert_num_queries: Any
) -> None:
    with django_assert_num_queries(2):
        publish("desk.ticket.closed", person="p", ticket=str(ticket.pk), minutes=1, actor=None)


# delivering


def test_deliveries_run_after_the_commit_under_the_publishing_request_id(
    ticket: Ticket, eager: Celery, django_capture_on_commit_callbacks: CaptureCallbacks
) -> None:
    with bound_request_id("req-family-1"), django_capture_on_commit_callbacks(execute=True):
        close(ticket, minutes=12)
    note = Note.objects.get()
    assert (note.ticket, note.person, note.request_id) == (
        str(ticket.pk),
        "person-1",
        "req-family-1",
    )
    assert Tally.objects.get(name="closed").count == 1
    rows = Delivery.objects.all()
    assert {(d.status, d.attempts) for d in rows} == {("delivered", 1)}
    assert all(d.delivered_at is not None for d in rows)


@pytest.mark.django_db(transaction=True)
def test_a_real_commit_delivers_with_eager_celery(eager: Celery) -> None:
    ticket = Ticket.objects.create(title="Real commit", requester="person-2")
    close(ticket, minutes=4)
    assert Note.objects.filter(ticket=str(ticket.pk)).exists()
    assert set(Delivery.objects.values_list("status", flat=True)) == {"delivered"}
    # Outside any transaction (autocommit) the event and its deliveries land together.
    publish("desk.ticket.closed", person="person-2", ticket="loose", minutes=0, actor=None)
    assert Note.objects.filter(ticket="loose").exists()


def _broken_dispatcher(event_id: str, *, countdown: float = 0) -> None:
    raise RuntimeError("a dispatcher bug")


@pytest.mark.django_db(transaction=True)
def test_a_dispatcher_that_raises_never_breaks_the_publishers_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ticket = Ticket.objects.create(title="Robust", requester="p")
    with override_settings(KARNI_EVENTS_DISPATCHER=_broken_dispatcher):
        close(ticket, minutes=1)
    ticket.refresh_from_db()
    assert ticket.status == "closed"
    assert set(Delivery.objects.values_list("status", flat=True)) == {"pending"}
    assert "a dispatcher bug" in caplog.text


def test_a_failing_subscriber_rolls_back_its_own_writes_only_and_is_retried(
    ticket: Ticket, eager: Celery, django_capture_on_commit_callbacks: CaptureCallbacks
) -> None:
    listeners.behaviour["fail"] = 1
    before = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        close(ticket, minutes=5)
    ticket.refresh_from_db()
    assert ticket.status == "closed"  # the publisher's work stands
    assert not Note.objects.exists()  # the subscriber's write was rolled back
    failed = Delivery.objects.get(subscriber=WRITE_NOTE)
    assert (failed.status, failed.attempts) == ("pending", 1)
    assert "the notes service is down" in failed.last_error
    assert before + dt.timedelta(seconds=9) < failed.next_attempt_at
    assert Delivery.objects.get(subscriber=TALLY).status == "delivered"

    assert deliver_event(str(failed.event_id)).delivered == []  # not due yet
    report = deliver_now()
    assert report.delivered == [WRITE_NOTE]
    assert Note.objects.count() == 1
    assert Delivery.objects.get(subscriber=WRITE_NOTE).last_error == ""


def test_a_delivery_fails_for_good_after_the_last_attempt_and_can_be_retried(
    ticket: Ticket, caplog: pytest.LogCaptureFixture
) -> None:
    listeners.behaviour["fail"] = 5
    close(ticket, minutes=5)
    with override_settings(KARNI_EVENTS_MAX_ATTEMPTS=2), caplog.at_level(logging.WARNING):
        assert deliver_now().retrying == [WRITE_NOTE]
        assert deliver_now().failed == [WRITE_NOTE]
        assert deliver_now().failed == []  # a failed delivery is not run again
    failed = Delivery.objects.get(subscriber=WRITE_NOTE)
    assert (failed.status, failed.attempts) == ("failed", 2)
    assert "failed for good" in caplog.text
    ok, detail = check_outbox()
    assert not ok
    assert "1 failed" in detail

    listeners.behaviour["fail"] = 0
    failed.retry()
    assert deliver_now().delivered == [WRITE_NOTE]
    assert check_outbox() == (True, "event deliveries up to date")


def test_a_delivered_event_is_never_run_twice(ticket: Ticket) -> None:
    close(ticket, minutes=1)
    event_id = str(OutboxEvent.objects.get().pk)
    first = deliver_event(event_id, force=True)
    again = deliver_event(event_id, force=True)
    assert sorted(first.delivered) == [TALLY, WRITE_NOTE]
    assert again.delivered == []
    assert Tally.objects.get(name="closed").count == 1


def test_once_says_yes_once_per_event_and_key(db: None) -> None:
    event_id = uuid.uuid4()
    assert once(event_id, "welcome") is True
    assert once(str(event_id), "welcome") is False
    assert once(event_id, "receipt") is True
    assert Handled.objects.count() == 2
    with pytest.raises(KarniError) as exc:
        once(event_id, "")
    assert _code(exc) == "E453"


def test_a_subscriber_missing_from_the_process_counts_as_a_failed_attempt(
    ticket: Ticket,
) -> None:
    close(ticket, minutes=1)
    Delivery.objects.filter(subscriber=TALLY).update(subscriber="notes.renamed")
    report = deliver_now()
    assert report.retrying == ["notes.renamed"]
    assert "No subscriber is named 'notes.renamed'" in (
        Delivery.objects.get(subscriber="notes.renamed").last_error
    )


def test_backoff_grows_four_times_and_stops_at_six_hours() -> None:
    assert [backoff(n).total_seconds() for n in (1, 2, 3, 4)] == [10, 40, 160, 640]
    assert backoff(30) == dt.timedelta(hours=6)


def test_a_subscriber_that_publishes_is_delivered_in_the_same_deliver_now(
    ticket: Ticket,
) -> None:
    registry = karni_events.declare.__globals__["registry"]
    declare("desk.note.filed", fields=["ticket"])
    filed: list[str] = []

    def file_it(event: Event) -> None:
        publish("desk.note.filed", ticket=event["ticket"], actor=None)

    def count_it(event: Event) -> None:
        filed.append(event["ticket"])

    subscribe("desk.ticket.closed", name="tests.chain.file")(file_it)
    subscribe("desk.note.filed", name="tests.chain.count")(count_it)
    try:
        close(ticket, minutes=1)
        deliver_now()
    finally:
        registry.remove_subscriber("tests.chain.file")
        registry.remove_subscriber("tests.chain.count")
        registry._declarations.pop("desk.note.filed", None)
    assert filed == [str(ticket.pk)]


# the sweep, a broker that is down, retention


def test_the_sweep_sends_overdue_events_only(ticket: Ticket, eager: Celery) -> None:
    close(ticket, minutes=1)  # no commit in a db test: nothing was sent
    assert sweep() == 0  # not a minute late yet
    assert sweep(older_than=0) == 1
    assert set(Delivery.objects.values_list("status", flat=True)) == {"delivered"}
    assert sweep(older_than=0) == 0


def test_a_broker_down_at_commit_leaves_the_event_for_the_sweep(
    ticket: Ticket,
    eager: Celery,
    django_capture_on_commit_callbacks: CaptureCallbacks,
    caplog: pytest.LogCaptureFixture,
) -> None:
    down = create_celery_app(
        "karni-family-events-down",
        broker_url="redis://127.0.0.1:1/0",
        task_always_eager=False,
        broker_connection_timeout=1,
        broker_connection_retry=False,
    )
    down.set_current()
    started = time.monotonic()
    try:
        with caplog.at_level(logging.WARNING, logger="karni.events"):
            with django_capture_on_commit_callbacks(execute=True):
                close(ticket, minutes=1)
    finally:
        eager.set_current()
    assert time.monotonic() - started < 15
    assert "was not handed to a worker" in caplog.text
    ticket.refresh_from_db()
    assert ticket.status == "closed"  # the publisher committed
    assert set(Delivery.objects.values_list("status", "attempts")) == {("pending", 0)}

    assert sweep(older_than=0) == 1  # the broker is back (eager here)
    assert set(Delivery.objects.values_list("status", flat=True)) == {"delivered"}
    assert Note.objects.count() == 1


@pytest.mark.skipif(
    not os.environ.get("KARNI_TEST_REDIS_URL"),
    reason="set KARNI_TEST_REDIS_URL (a Redis database the test may empty) to run it",
)
def test_a_real_broker_receives_the_event_after_the_commit(
    ticket: Ticket, eager: Celery, django_capture_on_commit_callbacks: CaptureCallbacks
) -> None:
    url = os.environ["KARNI_TEST_REDIS_URL"]
    app = create_celery_app("karni-family-events-redis", broker_url=url, task_always_eager=False)
    with app.connection_for_write() as conn:
        client = conn.default_channel.client
        client.delete("celery")
        app.set_current()
        try:
            with django_capture_on_commit_callbacks(execute=True):
                close(ticket, minutes=1)
        finally:
            eager.set_current()
        assert client.llen("celery") == 1  # the delivery task waits for a worker
        client.delete("celery")
    assert set(Delivery.objects.values_list("status", flat=True)) == {"pending"}
    from karni.outbox.tasks import deliver

    deliver.apply(args=(str(OutboxEvent.objects.get().pk),))  # what the worker runs
    assert set(Delivery.objects.values_list("status", flat=True)) == {"delivered"}


def test_retries_are_queued_through_the_dispatcher_outside_eager_mode(
    ticket: Ticket,
) -> None:
    sent: list[tuple[str, float]] = []
    listeners.behaviour["fail"] = 1
    close(ticket, minutes=1)
    event_id = str(OutboxEvent.objects.get().pk)
    lazy = create_celery_app("karni-family-events-lazy", task_always_eager=False)
    previous = celery_state.get_current_app()
    lazy.set_current()
    try:
        record = lambda e, countdown=0: sent.append((e, countdown))  # noqa: E731
        with override_settings(KARNI_EVENTS_DISPATCHER=record):
            from karni.outbox.tasks import deliver

            deliver.apply(args=(event_id,))
    finally:
        previous.set_current()
    assert len(sent) == 1
    assert sent[0][0] == event_id
    assert 5 < sent[0][1] <= 10


def test_prune_keeps_what_is_not_delivered(ticket: Ticket) -> None:
    close(ticket, minutes=1)
    deliver_now()
    listeners.behaviour["fail"] = 1
    close(Ticket.objects.create(title="Second", requester="p"), minutes=1)
    deliver_now()
    once(uuid.uuid4(), "old")
    old = timezone.now() - dt.timedelta(days=40)
    OutboxEvent.objects.update(occurred_at=old)
    Handled.objects.update(created_at=old)
    with override_settings(KARNI_EVENTS_RETENTION_DAYS=None):
        assert prune() == 0
    assert prune() == 1
    assert OutboxEvent.objects.count() == 1  # its note delivery is still pending
    assert not Handled.objects.filter(key="old").exists()


# without the outbox app


def test_without_the_outbox_app_subscribers_are_refused(
    ticket: Ticket, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(delivery, "outbox_installed", lambda: False)
    found = [m for m in check_event_bus() if m.id == "karni.E451"]
    assert len(found) == 1
    assert WRITE_NOTE in found[0].msg
    with pytest.raises(KarniError) as exc:
        close(ticket, minutes=1)
    assert _code(exc) == "E451"
    with pytest.raises(KarniError) as exc:
        once(uuid.uuid4(), "k")
    assert _code(exc) == "E451"

    registry = Registry()
    declare("desk.queue.emptied", fields=[], registry=registry)
    with capture_events() as published:
        publish("desk.queue.emptied", registry=registry)
    published.assert_published("desk.queue.emptied")
    assert not OutboxEvent.objects.exists()


# checks, listing, health


def test_a_dispatcher_that_cannot_be_imported_is_reported() -> None:
    with override_settings(KARNI_EVENTS_DISPATCHER="nowhere.at_all.dispatch"):
        ids = [m.id for m in check_event_bus()]
    assert "karni.E455" in ids


def test_a_subscriber_on_a_version_nobody_declares_is_warned() -> None:
    registry = karni_events.declare.__globals__["registry"]
    subscribe("desk.ticket.closed", version=3, name="tests.future")(lambda event: None)
    try:
        found = [m for m in check_event_bus() if m.id == "karni.W450"]
    finally:
        registry.remove_subscriber("tests.future")
    assert len(found) == 1
    assert "version 3" in found[0].msg


def test_the_listing_names_each_event_and_its_subscribers() -> None:
    lines = event_listing()
    assert f"desk.ticket.closed v1 (tests.deskapp.events): {TALLY}, {WRITE_NOTE}" in lines


def test_the_health_check_counts_stuck_deliveries(ticket: Ticket) -> None:
    close(ticket, minutes=1)
    assert check_outbox()[0] is True
    Delivery.objects.update(next_attempt_at=timezone.now() - dt.timedelta(minutes=11))
    ok, detail = check_outbox()
    assert not ok
    assert "2 waiting more than 10 minutes" in detail


def test_the_health_check_passes_without_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delivery, "outbox_installed", lambda: False)
    assert check_outbox() == (True, "karni.outbox is not installed")


# karni trace


def test_karni_trace_follows_an_event_to_its_deliveries(ticket: Ticket) -> None:
    from karni.debug.trace import render, story

    with bound_request_id("req-trace-events"):
        close(ticket, minutes=1)
    deliver_now()
    data = story("req-trace-events")
    assert data is not None
    names = [entry["event"] for entry in data["events"]]
    assert names.count("event.published") == 1
    assert names.count("event.delivery") == 2
    text = render(data)
    assert "desk.ticket.closed v1" in text
    assert f"{WRITE_NOTE} delivered" in text


# test helpers


def test_capture_events_reports_what_was_published_when_an_assertion_fails(
    ticket: Ticket,
) -> None:
    with capture_events() as published:
        close(ticket, minutes=7)
    assert len(published) == 1
    published.assert_published("desk.ticket.closed", count=1, minutes=7)
    with pytest.raises(KarniError) as exc:
        published.assert_published("desk.ticket.closed", minutes=8)
    assert _code(exc) == "E456"
    assert "'minutes': 7" in str(exc.value)
    with pytest.raises(KarniError) as exc:
        published.assert_not_published("desk.ticket.closed")
    assert _code(exc) == "E456"
    published.assert_not_published("desk.ticket.reopened")


def test_assert_events_declared_reads_the_apps_publish_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert assert_events_declared("deskapp") == ["desk.ticket.closed"]
    registry = karni_events.declare.__globals__["registry"]
    monkeypatch.setattr(registry, "declaration", lambda name, version=None: None)
    with pytest.raises(KarniError) as exc:
        assert_events_declared("deskapp")
    assert _code(exc) == "E456"
    assert "services.py" in str(exc.value)


# the admin


def test_the_admin_lists_events_and_retries_failed_deliveries(ticket: Ticket, client: Any) -> None:
    listeners.behaviour["fail"] = 5
    close(ticket, minutes=1)
    with override_settings(KARNI_EVENTS_MAX_ATTEMPTS=1):
        deliver_now()
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    client.force_login(root)
    page = client.get("/admin/karni_outbox/outboxevent/")
    assert page.status_code == 200
    assert "1 delivered, 1 failed" in page.content.decode()
    page = client.get("/admin/karni_outbox/delivery/?status__exact=failed")
    assert page.status_code == 200
    assert WRITE_NOTE in page.content.decode()
    failed = Delivery.objects.get(status="failed")
    listeners.behaviour["fail"] = 0
    response = client.post(
        "/admin/karni_outbox/delivery/",
        {"action": "retry", "_selected_action": [failed.pk]},
    )
    assert response.status_code == 302
    failed.refresh_from_db()
    assert failed.status == "pending"


# two workers on one delivery (PostgreSQL row locks)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="SKIP LOCKED is PostgreSQL's")
def test_a_delivery_another_worker_holds_is_skipped() -> None:
    ticket = Ticket.objects.create(title="Locked", requester="p")
    with override_settings(KARNI_EVENTS_DISPATCHER=lambda e, countdown=0: None):
        close(ticket, minutes=1)
    event_id = str(OutboxEvent.objects.get().pk)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        from django.db import connections

        try:
            with transaction.atomic():
                list(Delivery.objects.select_for_update().filter(subscriber=WRITE_NOTE))
                held.set()
                release.wait(10)
        finally:
            connections.close_all()

    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert held.wait(10)
        report = deliver_event(event_id, force=True)
    finally:
        release.set()
        worker.join(10)
    assert report.delivered == [TALLY]
    assert Delivery.objects.get(subscriber=WRITE_NOTE).status == "pending"


# karni check


def test_karni_check_lists_the_events_and_passes(db: None) -> None:
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("karni_check", stdout=out, stderr=StringIO())
    text = out.getvalue()
    assert f"events: desk.ticket.closed v1 (tests.deskapp.events): {TALLY}, {WRITE_NOTE}" in text
    assert "events: absent.thing.happened v1 is not declared here" in text
    assert "backend checks: ok" in text
