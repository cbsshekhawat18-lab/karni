---
description: "Family events in Karni (experimental): one app reacts to another without importing it. Declare an event, publish it inside the writer's transaction into an outbox, and subscribe by name. Delivery runs after the commit in a Celery worker, is retried with backoff and happens at least once."
---

# Family events

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    `declare`, `publish`, `subscribe`, `once`, `Event`, `Declaration`,
    `Subscriber`, `Registry` and `CONTRACT` in `karni.events`, the
    `karni.outbox` app (its models `OutboxEvent`, `Delivery` and `Handled`,
    its admin, tasks, beat entries, `karni.outbox.delivery`,
    `karni.outbox.dispatch`, `karni.outbox.checks` and
    `karni.outbox.health`), the `KARNI_EVENTS_DISPATCHER`,
    `KARNI_EVENTS_MAX_ATTEMPTS` and `KARNI_EVENTS_RETENTION_DAYS` settings,
    the `events:` lines of `karni check`, and `capture_events`, `deliver_now`
    and `assert_events_declared` in `karni.testing`. They may change in a minor
    release, and each change is in the CHANGELOG. The error codes keep their
    meaning. The contract's version is `karni.events.CONTRACT` (1).

A project can hold several parts: a shop, a booking app, a CRM. Each part
works alone, and when two are installed together one reacts to what the other
did: a paid order gives the buyer a CRM profile, a cancelled booking lands on
the person's timeline. Family events are how that happens without one part
importing the other:

- the part that acts **declares** each event it publishes and **publishes** it
  inside the transaction that made the change;
- a part that reacts **subscribes** to the event by its name, and never
  imports the publisher. When the publisher is not installed, the subscriber
  is never called and nothing fails.

Delivery goes through an **outbox** in the same database. The event is written
in the publisher's transaction, so it exists exactly when the change
committed. After the commit, a Celery worker delivers it to each subscriber in
its own transaction, so a subscriber that fails never rolls back the
publisher's work. A failed delivery is retried with backoff. When the broker is
down at commit time, a beat task sends the event once it is back.

For a part's own rules inside its own transaction, keep using
[model listeners and signals](events.md). The bus is for one part reacting to
another.

## Install the outbox

The outbox is a core app a project adds when a part publishes or subscribes:

```python
# config/settings.py
INSTALLED_APPS += [
    "karni.outbox",
]
```

Then run `migrate`. A project without it gains no tables. In such a project
an event that nobody subscribes to is published for free, and a subscriber is
refused at startup with `karni.E451`.

Run a Celery worker and beat, as the [scheduling](scheduling.md) page shows:
the worker delivers, and beat runs the sweep every minute.

## Declare

A publisher declares each event in its app's `events.py`, which Karni imports
at startup:

```python
# desk/events.py
from karni.events import declare

declare(
    "desk.ticket.closed",
    version=1,
    fields={
        "ticket": "the ticket's id",
        "minutes": "minutes the ticket was open, a whole number",
    },
    person="person",
    describe="Staff closed a ticket.",
)
```

- **The name** is `<prefix>.<record>.<moment>`, in lower case, with the moment
  in the past tense: `shop.order.paid`, `bookings.booking.cancelled`,
  `courses.lesson.completed`. The prefix is the app label or the module's
  name. One part owns each name.
- **The version** says which payload shape this is, from 1. When the shape
  changes, declare version 2 next to version 1 and publish both until every
  subscriber reads version 2.
- **The fields** are the payload's own values, each with what it holds.
  Every declared field is passed to `publish()`.
- **`person`** says where the person the event is about comes from:
  `"person"` (the `person=` argument of `publish()`) or one of the fields.
  When it is set, a publish without a person is refused. Leave it out for an
  event where the person is optional.
- **`timeline`** is read by the [timeline](timeline.md): a title template, or
  a mapping of its options. With `karni.timeline` installed, each event
  then writes a timeline entry. The bus itself does not read it.
- **`describe`** says in one line when the event happens. `karni check`
  shows it.

## Publish

Publish inside the transaction that made the change:

```python
# desk/services.py
from django.db import transaction

from karni.events import publish


def close(ticket, minutes):
    with transaction.atomic():
        ticket.status = "closed"
        ticket.save(update_fields=["status", "updated_at"])
        publish(
            "desk.ticket.closed",
            subject=ticket,
            person=ticket.requester_id,
            ticket=str(ticket.pk),
            minutes=minutes,
        )
```

`publish()` writes one outbox row and one delivery row per subscriber in the
current transaction: two queries, however many subscribers there are. A
rolled-back transaction publishes nothing. The commit hands the event to the
dispatcher.

Every payload carries these fields, then the declared ones:

| Field | What it holds |
|---|---|
| `id` | The event's own id (a UUID). A subscriber uses it to stay idempotent. |
| `name`, `version` | The event and its payload version. |
| `occurred_at` | When it was published, ISO 8601. |
| `actor` | The id of the user who acted: the current request's user unless `actor=` says otherwise, or null. |
| `person` | The id of the person the event is about, or null. |
| `subject` | `{"model": "app_label.model", "id": "..."}` of the record the event is about, or null. |
| `request_id` | The id of the request or task that published it, so `karni trace` follows the event to its deliveries. |

The declared fields are plain JSON values: ids, states and amounts. A
decimal, a UUID and a date are written as strings for you
(`Decimal("12.50")` becomes `"12.50"`). A model instance is refused
(`karni.E453`): pass its id. A subscriber that needs more asks the contract's
service, never the publisher's models.

## Subscribe

A subscriber lives in its app's `listeners.py` and names the event as a
string:

```python
# notes/listeners.py
from karni.events import Event, subscribe

from notes.models import Note


@subscribe("desk.ticket.closed", version=1)
def write_note(event: Event) -> None:
    Note.objects.get_or_create(
        event_id=event.id,
        defaults={"ticket": event["ticket"], "person": event.person or ""},
    )
```

`event["ticket"]` reads a declared field, and `event.id`, `event.person`,
`event.subject` and `event.actor` the common ones. `event.payload` is the
whole event as JSON.

A subscriber is named by its dotted path (`notes.listeners.write_note`), and
each delivery row stores that name. Define it at the top level of the module.
Pass `name="notes.write_note"` to keep its deliveries when the function moves.

## Delivery

- **After the commit.** `KARNI_EVENTS_DISPATCHER` (by default
  `karni.outbox.dispatch.celery`) queues the task
  `karni.outbox.tasks.deliver`. With `CELERY_TASK_ALWAYS_EAGER` (tests, a
  project run without a worker) delivery runs right after the commit, in the
  process that committed.
- **In development, no worker needed.** While `DEBUG` is on, the default
  dispatcher is `karni.outbox.dispatch.inline`: delivery runs right after the
  commit, in the process that committed, as eager mode does. So a
  `runserver` with no Celery worker fills the timeline and the inbox at
  once. `KARNI_EVENTS_INLINE` decides it: unset (`None`) follows `DEBUG`,
  `True` does the same in a small deployment that runs no broker and no
  worker, `False` keeps Celery even in `DEBUG`. A dispatcher of your own
  (`KARNI_EVENTS_DISPATCHER`) is used either way, and production (`DEBUG`
  off, the switch unset) queues the Celery task as before. A retry due later
  is left to the sweep.
- **One transaction per subscriber.** Each subscriber runs inside a savepoint
  of the transaction that marks its delivery delivered, under a lock on that
  delivery's row only (`SKIP LOCKED` on PostgreSQL). Its writes and the mark
  commit together. When it raises, its writes roll back, the other
  subscribers of the same event still run, and the publisher's work stands.
- **Retries.** A failed delivery is due again after 10 seconds, then 40, 160,
  640 and so on, four times longer each time and never more than 6 hours.
  After `KARNI_EVENTS_MAX_ATTEMPTS` runs (8 by default) it is marked
  `failed`, logged as an error on the `karni.events` logger, listed in the
  admin and counted by the health check.
- **A broker that is down.** When the commit cannot reach the broker, the
  dispatcher logs a warning and the event stays in the outbox. The beat entry
  `karni-events-sweep` runs every minute and sends every event whose delivery
  is more than a minute overdue.
- **At least once.** The sweep can send an event the commit already sent, and
  a worker can stop after a subscriber sent an email. A delivered row never
  runs again, but a subscriber keeps its work idempotent: a unique key on its
  own row (as `Note.event_id` above), or `once()`:

  ```python
  from karni.events import once


  @subscribe("desk.ticket.closed", version=1)
  def count_closures(event: Event) -> None:
      if once(event, "tally"):
          Tally.objects.filter(name="closed").update(count=F("count") + 1)
  ```

  `once(event, key)` is true the first time it sees the pair and false after.
  Its mark is written in the current transaction, so it rolls back with the
  work it guards.
- **Order** is best effort, per subject. A subscriber that cares about order
  reads the current state through the contract's service.
- **The request id.** A subscriber runs under the publishing request's id, so
  its logs, its email and its change history carry it.
- **Retention.** The beat entry `karni-events-prune` deletes delivered events
  older than `KARNI_EVENTS_RETENTION_DAYS` (30 by default). Events with a
  pending or failed delivery stay. `None` keeps everything.

## The admin, the health check, karni check and karni trace

- **Admin.** *Karni events* has two lists. *Events* shows every published
  event with how many deliveries are delivered, pending and failed, and each
  event's page shows its payload and its deliveries. *Deliveries* filters by
  status and subscriber and shows the last error. Its action *Retry selected
  deliveries now* makes failed or pending deliveries due and sends their
  events again. Nothing is edited by hand.
- **Health check.** Add it to the checks `/health/ready/` runs:

  ```python
  KARNI_HEALTH_CHECKS = [*KARNI_HEALTH_CHECKS, "karni.outbox.health.check_outbox"]
  ```

  It fails while a delivery is failed or a pending one is more than 10
  minutes overdue (no worker or no beat). Keep it out of
  `KARNI_READYZ_CHECKS`: a subscriber's failure should not take the web
  process out of rotation.
- **`karni check`** prints one `events:` line per declared event with its
  subscribers, and one for each event a subscriber waits for that no
  installed part declares. It fails on `karni.E451` (subscribers without the
  outbox) and `karni.E455` (a dispatcher that cannot be imported), and warns
  with `karni.W450` when a subscriber reads a version its event does not have.
- **`karni trace <request id>`** lists the events the request published
  (`event.published`) and each delivery's state (`event.delivery`), read from
  the outbox. It works in production too, without the development capture.

## Testing

```python
from karni.testing import capture_events, deliver_now


def test_closing_a_ticket_notes_it(db, ticket):
    with capture_events() as published:
        close(ticket, minutes=12)
    published.assert_published("desk.ticket.closed", subject=ticket, minutes=12)

    deliver_now()
    assert Note.objects.count() == 1
```

- `capture_events()` collects every event published in its block, with or
  without the outbox installed. `assert_published(name, **values)` compares
  values the way `publish()` writes them (an instance as its id, a decimal as
  a string). `count=`, `subject=`, `person=`, `actor=` and `version=` narrow
  it. `assert_not_published(name)` checks for none.
- `deliver_now()` runs every pending delivery now, in the test's process,
  backoff ignored. A test inside pytest-django's `db` transaction never
  commits, so nothing is delivered until it runs. Events the subscribers
  publish are delivered in the same call. It returns what was delivered,
  retried and failed.
- `assert_events_declared("desk")` reads the app's code and fails when a
  `publish("<name>")` names an event nothing declares.

A test that wants the real commit path uses
`django_capture_on_commit_callbacks(execute=True)` or
`@pytest.mark.django_db(transaction=True)` with eager Celery.

## Events of the modules

karni-payments publishes these when a payment's or a refund's status moves
(`karni_payments/listeners.py`):

| Event | Fields |
|---|---|
| `payments.payment.succeeded` | `payment`, `amount`, `currency` |
| `payments.payment.failed` | `payment`, `amount` |
| `payments.refund.succeeded` | `refund`, `payment`, `amount` |

Their subject is the payment (or the refund). The person is the payer's
person when `karni.people` is installed and the payment's user is linked to
one, else empty. `payments.payment.succeeded` names a timeline title.

The [people contract](people.md#events) publishes `people.person.created`,
`people.person.linked`, `people.person.merged`, `people.person.erased`,
`people.organisation.created` and `people.organisation.merged`
(`karni/people/events.py`). The person of a person's event is that person
(the kept one for a merge), and an organisation's events have none.

## Escape hatches

- **`KARNI_EVENTS_DISPATCHER`** names the function that hands a committed
  event to a worker, `(event_id, *, countdown=0)`. Point it at your own to
  route deliveries to a queue of their own. It must not raise for a broker
  that is down: the sweep sends the event later.
- **The beat entries** `karni-events-sweep` and `karni-events-prune` are
  retimed or turned off with `CELERY_BEAT_SCHEDULE`, like any
  [declared schedule](scheduling.md).
- **`karni.outbox.delivery`** has `deliver_event`, `sweep` and `prune` as plain
  functions, each taking the database alias (`using=`).
- **`registry=`** on `declare`, `subscribe` and `publish` takes a `Registry`
  of your own.
- **Plain signals and model listeners** keep working next to the bus, for
  work that must happen inside the writer's transaction.

## What the bus is not

- Not a source of truth. The outbox is a delivery log, pruned after the
  retention window. Records stay in their own tables.
- Not for field changes. Events are business moments. The
  [change history](change-history.md) records field changes.
- Not a second broker. It uses the database and the Celery worker a project
  already runs.
