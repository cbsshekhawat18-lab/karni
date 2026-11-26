"""Writing family events to the outbox and delivering them to subscribers.

* :func:`store` runs inside :func:`karni.events.publish`: one
  :class:`~karni.outbox.models.OutboxEvent` row and one
  :class:`~karni.outbox.models.Delivery` row per subscriber, in the
  publisher's transaction, then :func:`dispatch` once it commits.
* :func:`deliver_event` runs each due delivery of one event: the subscriber
  is called inside a savepoint of the transaction that marks the delivery,
  so its writes and the ``delivered`` mark commit together. A failure rolls
  back the subscriber's writes only, and the delivery is due again after
  :func:`backoff`, until ``KARNI_EVENTS_MAX_ATTEMPTS`` makes it ``failed``.
* :func:`sweep` sends every event whose delivery is overdue: what the commit
  could not send because the broker was down, and retries whose message was
  lost. Beat runs it every minute (:mod:`karni.outbox.schedules`).
* :func:`prune` deletes delivered events older than
  ``KARNI_EVENTS_RETENTION_DAYS``. Events with a pending or failed delivery
  stay.

Two workers may hold the same event (the commit and the sweep both sent
it): each delivery row is locked while it runs (``SKIP LOCKED`` on
PostgreSQL), and a delivered row is never run again. A subscriber still
gets an event at least once, so it keeps its work idempotent (a unique key
on its own row, or :func:`karni.events.once`).

Override / escape hatch: ``KARNI_EVENTS_DISPATCHER`` (:mod:`karni.outbox.dispatch`)
decides how a committed event reaches a worker. These functions are plain
and take the database alias (``using=``) for a project that keeps the
outbox on another database.
"""

from __future__ import annotations

import datetime as dt
import logging
import traceback
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from django.apps import apps
from django.conf import settings
from django.db import connections, router, transaction
from django.db.models import Min
from django.utils import timezone

from karni.exceptions import KarniImproperlyConfigured

if TYPE_CHECKING:
    from karni.outbox.bus import Event, Registry, Subscriber

__all__ = [
    "BACKOFF_CAP",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETENTION_DAYS",
    "SWEEP_AFTER",
    "DeliveryReport",
    "backoff",
    "deliver_event",
    "dispatch",
    "max_attempts",
    "outbox_installed",
    "prune",
    "require_outbox",
    "retention_days",
    "store",
    "sweep",
]

logger = logging.getLogger("karni.events")

DEFAULT_MAX_ATTEMPTS: Final = 8
DEFAULT_RETENTION_DAYS: Final = 30
#: Seconds a pending delivery may be overdue before the sweep sends it again
#: (the commit's own message usually arrives first).
SWEEP_AFTER: Final = 60
#: Events one sweep sends at most. The next minute's sweep takes the rest.
SWEEP_BATCH: Final = 500
#: The first retry waits this many seconds, each next one four times longer.
BACKOFF_BASE: Final = 10
BACKOFF_FACTOR: Final = 4
#: No retry waits longer than six hours.
BACKOFF_CAP: Final = 6 * 3600
_ERROR_MAX: Final = 4000


def outbox_installed() -> bool:
    """Whether ``karni.outbox`` is in ``INSTALLED_APPS``."""
    return apps.is_installed("karni.outbox")


def require_outbox(what: str) -> None:
    """E451 when ``karni.outbox`` is not installed: ``what`` needs its tables."""
    if not outbox_installed():
        raise KarniImproperlyConfigured(
            f"karni.events: {what} needs the outbox, and 'karni.outbox' is not in "
            "INSTALLED_APPS. Add it there and run migrate: subscribers are delivered from "
            "its tables.",
            code="E451",
        )


def max_attempts() -> int:
    """``KARNI_EVENTS_MAX_ATTEMPTS``: runs of one delivery before it is ``failed``."""
    return int(getattr(settings, "KARNI_EVENTS_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))


def retention_days() -> int | None:
    """``KARNI_EVENTS_RETENTION_DAYS``: days a delivered event is kept, ``None`` for ever."""
    days = getattr(settings, "KARNI_EVENTS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
    return None if days is None else int(days)


def backoff(attempts: int) -> dt.timedelta:
    """How long a delivery waits after its ``attempts``-th failure: 10s, 40s, 160s, ... 6h."""
    seconds = BACKOFF_BASE * BACKOFF_FACTOR ** max(attempts - 1, 0)
    return dt.timedelta(seconds=min(seconds, BACKOFF_CAP))


# writing


def store(event: Event, subscribers: Sequence[Subscriber], *, using: str | None = None) -> None:
    """Write ``event`` and one delivery per subscriber in the current transaction.

    Without ``karni.outbox`` installed, an event nobody subscribes to is
    dropped (there is nothing to deliver), and one with subscribers raises
    E451. With it, the event row is written even with no subscriber, so the
    admin and ``karni trace`` show every business moment.
    """
    if not outbox_installed():
        if subscribers:
            names = ", ".join(s.name for s in subscribers)
            require_outbox(f"publishing {event.name!r} to its subscribers ({names})")
        return
    from karni.outbox.models import Delivery, OutboxEvent

    alias = using or router.db_for_write(OutboxEvent)
    subject = event.subject or {}
    # One unit even outside a transaction: the event never exists without its deliveries.
    with transaction.atomic(using=alias, savepoint=False):
        OutboxEvent.objects.using(alias).create(
            id=event.id,
            name=event.name,
            version=event.version,
            occurred_at=event.occurred_at,
            subject_model=subject.get("model", ""),
            subject_id=subject.get("id", ""),
            person_id=event.person or "",
            actor_id=event.actor or "",
            request_id=event.request_id or "",
            payload=event.payload,
        )
        if subscribers:
            Delivery.objects.using(alias).bulk_create(
                [
                    Delivery(
                        event_id=event.id,
                        subscriber=subscriber.name,
                        next_attempt_at=event.occurred_at,
                        created_at=event.occurred_at,
                    )
                    for subscriber in subscribers
                ]
            )
    if not subscribers:
        return
    event_id = event.id

    def send_after_commit() -> None:
        dispatch(event_id)

    # robust: a dispatcher that raises is logged and never fails the publisher's commit.
    transaction.on_commit(send_after_commit, using=alias, robust=True)


def dispatch(event_id: str, *, countdown: float = 0) -> None:
    """Hand ``event_id`` to ``KARNI_EVENTS_DISPATCHER`` (a Celery task by default)."""
    from karni.outbox.dispatch import dispatcher

    dispatcher()(str(event_id), countdown=countdown)


# delivering


@dataclass
class DeliveryReport:
    """What one run of :func:`deliver_event` (or :func:`sweep`) did."""

    delivered: list[str] = field(default_factory=list)
    retrying: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    #: When the earliest delivery still pending is due, or ``None``.
    next_attempt_at: dt.datetime | None = None

    def add(self, other: DeliveryReport) -> None:
        self.delivered += other.delivered
        self.retrying += other.retrying
        self.failed += other.failed
        if other.next_attempt_at is not None and (
            self.next_attempt_at is None or other.next_attempt_at < self.next_attempt_at
        ):
            self.next_attempt_at = other.next_attempt_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "delivered": list(self.delivered),
            "retrying": list(self.retrying),
            "failed": list(self.failed),
            "next_attempt_at": self.next_attempt_at.isoformat() if self.next_attempt_at else None,
        }


@contextmanager
def _under_request_id(request_id: str | None) -> Iterator[None]:
    """Run a subscriber under the publishing request's id, so its logs and email carry it."""
    from karni.tracing import bound_request_id, is_valid_request_id

    if request_id and is_valid_request_id(request_id):
        with bound_request_id(request_id):
            yield
    else:
        yield


def _error_text(exc: BaseException) -> str:
    text = "".join(traceback.format_exception(exc, limit=8))
    return text[-_ERROR_MAX:]


def _attempt(
    pk: int, event: Event, alias: str, source: Registry, *, force: bool
) -> tuple[str, str] | None:
    """Run one delivery under its row lock: ``(status, subscriber)``, or None when not due."""
    from karni.outbox.models import Delivery

    features = connections[alias].features
    with transaction.atomic(using=alias):
        rows = Delivery.objects.using(alias).filter(pk=pk, status=Delivery.Status.PENDING)
        if features.has_select_for_update_skip_locked:
            # This delivery's row only: another worker's delivery of the same event runs on.
            of = ("self",) if features.has_select_for_update_of else ()
            rows = rows.select_for_update(skip_locked=True, of=of)
        delivery = rows.order_by().first()
        now = timezone.now()
        if delivery is None or (not force and delivery.next_attempt_at > now):
            return None
        subscriber = source.subscriber(delivery.subscriber)
        delivery.attempts = min(delivery.attempts + 1, 32767)
        error: str | None = None
        if subscriber is None:
            error = (
                f"No subscriber is named {delivery.subscriber!r} in this process. It was "
                "renamed or removed, or this worker runs older code: keep its name= while "
                "events wait for it."
            )
        else:
            try:
                with _under_request_id(event.request_id), transaction.atomic(using=alias):
                    subscriber.func(event)
            except Exception as exc:  # noqa: BLE001 - a subscriber's failure is recorded, never raised
                error = _error_text(exc)
        if error is None:
            delivery.status = Delivery.Status.DELIVERED
            delivery.delivered_at = now
            delivery.last_error = ""
        elif delivery.attempts >= max_attempts():
            delivery.status = Delivery.Status.FAILED
            delivery.last_error = error
            logger.error(
                "karni.events: %s failed for good on %s (%s) after %s attempts. Fix it, then "
                "use Retry on the delivery in the admin.\n%s",
                delivery.subscriber,
                event.name,
                event.id,
                delivery.attempts,
                error,
            )
        else:
            delivery.next_attempt_at = now + backoff(delivery.attempts)
            delivery.last_error = error
            logger.warning(
                "karni.events: %s failed on %s (%s), attempt %s of %s. Retried at %s.\n%s",
                delivery.subscriber,
                event.name,
                event.id,
                delivery.attempts,
                max_attempts(),
                delivery.next_attempt_at.isoformat(),
                error,
            )
        delivery.save(
            using=alias,
            update_fields=[
                "status",
                "attempts",
                "next_attempt_at",
                "delivered_at",
                "last_error",
                "updated_at",
            ],
        )
        return str(delivery.status), delivery.subscriber


def deliver_event(
    event_id: str,
    *,
    force: bool = False,
    using: str | None = None,
    registry: Registry | None = None,
) -> DeliveryReport:
    """Run every due delivery of ``event_id`` now, in this process.

    ``force`` runs pending deliveries whose retry is not due yet (a test, or
    a person who fixed the subscriber). A delivered or failed delivery is
    never run here: the admin's *Retry* makes a failed one pending again.
    """
    from karni.outbox.bus import Event
    from karni.outbox.bus import registry as default_registry
    from karni.outbox.models import Delivery, OutboxEvent

    alias = using or router.db_for_write(OutboxEvent)
    report = DeliveryReport()
    row = OutboxEvent.objects.using(alias).filter(pk=event_id).first()
    if row is None:
        return report
    event = Event.from_payload(row.payload)
    source = registry if registry is not None else default_registry
    pending = Delivery.objects.using(alias).filter(event_id=row.pk, status=Delivery.Status.PENDING)
    due = pending if force else pending.filter(next_attempt_at__lte=timezone.now())
    for pk in list(due.order_by("subscriber").values_list("pk", flat=True)):
        outcome = _attempt(pk, event, alias, source, force=force)
        if outcome is None:
            continue
        status, subscriber = outcome
        if status == Delivery.Status.DELIVERED:
            report.delivered.append(subscriber)
        elif status == Delivery.Status.FAILED:
            report.failed.append(subscriber)
        else:
            report.retrying.append(subscriber)
    report.next_attempt_at = pending.aggregate(due=Min("next_attempt_at"))["due"]
    return report


def overdue_events(
    *, older_than: float = SWEEP_AFTER, limit: int = SWEEP_BATCH, using: str | None = None
) -> list[str]:
    """Ids of events with a pending delivery overdue by ``older_than`` seconds, oldest first."""
    from karni.outbox.models import Delivery, OutboxEvent

    alias = using or router.db_for_write(OutboxEvent)
    cutoff = timezone.now() - dt.timedelta(seconds=older_than)
    ids = (
        OutboxEvent.objects.using(alias)
        .filter(
            deliveries__status=Delivery.Status.PENDING,
            deliveries__next_attempt_at__lte=cutoff,
        )
        .order_by("occurred_at")
        .values_list("pk", flat=True)
        .distinct()[:limit]
    )
    return [str(pk) for pk in ids]


def sweep(
    *, older_than: float = SWEEP_AFTER, limit: int = SWEEP_BATCH, using: str | None = None
) -> int:
    """Send every event with an overdue delivery again, and return how many were sent.

    The beat entry ``karni-events-sweep`` runs it every minute. An event the
    commit already sent but a busy worker has not reached yet may be sent
    twice: the delivery's row lock and status keep it from running twice.
    """
    ids = overdue_events(older_than=older_than, limit=limit, using=using)
    for event_id in ids:
        dispatch(event_id)
    return len(ids)


def prune(days: int | None = None, *, using: str | None = None) -> int:
    """Delete delivered events older than ``days`` (``KARNI_EVENTS_RETENTION_DAYS``).

    An event with a pending or failed delivery stays, whatever its age.
    Keys of :func:`karni.events.once` older than the window go too. Returns
    the number of events deleted, 0 while retention is ``None``.
    """
    from karni.outbox.models import Delivery, Handled, OutboxEvent

    window = days if days is not None else retention_days()
    if window is None:
        return 0
    alias = using or router.db_for_write(OutboxEvent)
    cutoff = timezone.now() - dt.timedelta(days=int(window))
    open_events = Delivery.objects.using(alias).filter(
        status__in=[Delivery.Status.PENDING, Delivery.Status.FAILED]
    )
    old = OutboxEvent.objects.using(alias).filter(occurred_at__lt=cutoff)
    _, deleted = old.exclude(pk__in=open_events.values("event_id")).delete()
    Handled.objects.using(alias).filter(created_at__lt=cutoff).delete()
    return int(deleted.get(OutboxEvent._meta.label, 0))
