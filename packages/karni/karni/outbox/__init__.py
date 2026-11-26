"""Family events with an outbox: one part reacts to another without importing it.

The API lives in :mod:`karni.events` (``declare``, ``publish``, ``subscribe``,
``once``). This app keeps the outbox those calls write to and deliver from:

* :class:`~karni.outbox.models.OutboxEvent`: one row per published event,
  written in the publisher's transaction, so an event exists exactly when the
  change committed.
* :class:`~karni.outbox.models.Delivery`: one row per subscriber of that
  event, with its attempts, its next attempt and its last error.
* :class:`~karni.outbox.models.Handled`: the keys :func:`karni.events.once`
  has seen, for a subscriber that must do something once per event.

After the commit, ``KARNI_EVENTS_DISPATCHER`` (a Celery task by default)
delivers the event: each subscriber runs in its own transaction, in a worker,
and a failure is retried with backoff up to ``KARNI_EVENTS_MAX_ATTEMPTS``,
then marked failed. A beat task every minute sends what the commit could not
(the broker was down), and a daily one prunes delivered events after
``KARNI_EVENTS_RETENTION_DAYS``. Delivery is at least once.

A project adds ``"karni.outbox"`` to ``INSTALLED_APPS`` when a part publishes
or subscribes, so a project without family events gains no tables. Without
the app, publishing an event nobody subscribes to costs nothing, and a
subscriber is refused at startup (``karni.E451``).

Override / escape hatches: ``KARNI_EVENTS_DISPATCHER`` replaces how a
committed event reaches a worker, :func:`karni.outbox.delivery.deliver_event`
and :func:`~karni.outbox.delivery.sweep` are plain functions, the beat entries
(``karni-events-sweep`` and ``karni-events-prune``) are retimed or turned off
with ``CELERY_BEAT_SCHEDULE``, and plain Django signals and model listeners
keep working next to the bus. See docs/family-events.md.
"""

from __future__ import annotations

__all__ = ["APP", "LABEL"]

#: The dotted path a project adds to ``INSTALLED_APPS``.
APP = "karni.outbox"
#: The app label of the outbox tables.
LABEL = "karni_outbox"
