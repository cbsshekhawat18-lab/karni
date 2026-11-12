"""Experimental. How a committed family event reaches a worker: ``KARNI_EVENTS_DISPATCHER``.

A dispatcher is a callable ``(event_id: str, *, countdown: float = 0) ->
None``. Karni calls it once the publishing transaction commits, and again
for a retry that is due later (``countdown`` seconds from now) and for each
event the sweep finds overdue. The default, :func:`celery`, queues
:func:`karni.outbox.tasks.deliver`. With ``CELERY_TASK_ALWAYS_EAGER`` (tests,
a project run without a worker) that task runs right away, in the process
that committed.

A dispatcher must not raise for a broker that is down: the event is already
safe in the outbox, and the sweep sends it again. :func:`celery` logs the
failure on ``karni.events`` and returns.

Override / escape hatch: point ``KARNI_EVENTS_DISPATCHER`` at your own
callable, for example to route deliveries to a queue of their own::

    def to_events_queue(event_id: str, *, countdown: float = 0) -> None:
        deliver.apply_async((event_id,), countdown=countdown or None, queue="events")
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Final

from django.conf import settings
from django.utils.module_loading import import_string

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["DEFAULT", "SETTING", "celery", "dispatcher", "load"]

logger = logging.getLogger("karni.events")

SETTING: Final = "KARNI_EVENTS_DISPATCHER"
DEFAULT: Final = "karni.outbox.dispatch.celery"

Dispatcher = Callable[..., Any]


def celery(event_id: str, *, countdown: float = 0) -> None:
    """Queue :func:`karni.outbox.tasks.deliver` for ``event_id``. Log a failure, never raise."""
    from karni.outbox.tasks import deliver

    try:
        deliver.apply_async(args=(event_id,), countdown=countdown or None)
    except Exception as exc:  # noqa: BLE001 - the outbox keeps the event, the sweep sends it
        logger.warning(
            "karni.events: event %s was not handed to a worker (%s: %s). It stays in the "
            "outbox, and the sweep (karni-events-sweep, every minute) sends it once the "
            "broker answers.",
            event_id,
            type(exc).__name__,
            exc,
        )


@lru_cache(maxsize=8)
def load(path: str) -> Dispatcher:
    """The dispatcher at the dotted ``path``. E455 when it cannot be imported or called."""
    try:
        found = import_string(path)
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"{SETTING} = {path!r} cannot be imported ({exc}). Name a function as "
            f"'package.module.function', or remove the setting for the default ({DEFAULT!r}).",
            code="E455",
        ) from exc
    if not callable(found):
        raise KarniImproperlyConfigured(
            f"{SETTING} = {path!r} is {found!r}, which is not callable. Name a function "
            "taking (event_id, *, countdown=0).",
            code="E455",
        )
    return found  # type: ignore[no-any-return]


def dispatcher() -> Dispatcher:
    """The configured dispatcher (``KARNI_EVENTS_DISPATCHER``, :func:`celery` by default)."""
    path = getattr(settings, SETTING, None) or DEFAULT
    if callable(path):
        return path  # type: ignore[no-any-return]
    return load(str(path))
