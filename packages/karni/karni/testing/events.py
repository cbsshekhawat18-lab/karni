"""Test helpers for family events: what was published, delivered now, declared.

::

    from karni.testing import capture_events, deliver_now

    def test_closing_a_ticket_publishes_and_notes_it(db):
        with capture_events() as published:
            close(ticket, minutes=12)
        published.assert_published("desk.ticket.closed", subject=ticket, minutes=12)

        deliver_now()  # every pending delivery, in this process, retries included
        assert Note.objects.count() == 1

* :func:`capture_events` collects every event published in its block, with
  or without ``karni.outbox`` installed, rolled back or not.
* :func:`deliver_now` runs every pending delivery at once, in the test's
  process and transaction, ignoring the retry backoff: a test inside
  pytest-django's ``db`` transaction never commits, so the commit hook never
  sends anything by itself. Events published by the subscribers it runs are
  delivered in the same call.
* :func:`assert_events_declared` reads an app's code: every
  ``publish("<name>")`` it makes names a declared event (and version).

Each failure raises ``KarniAssertionError`` with code E456 and lists what
was found.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from karni.exceptions import KarniAssertionError
from karni.outbox.bus import Event

__all__ = [
    "PublishedEvents",
    "assert_events_declared",
    "capture_events",
    "deliver_now",
]

_ANY: Any = object()


def _show(events: list[Event]) -> str:
    if not events:
        return "nothing was published"
    return "published: " + " | ".join(
        f"{e.name} v{e.version} subject={e.subject_ref} person={e.person} {dict(e.data)}"
        for e in events
    )


@dataclass
class PublishedEvents:
    """The events published inside :func:`capture_events`, in order."""

    events: list[Event] = field(default_factory=list)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def named(self, name: str) -> list[Event]:
        """The events called ``name``, in the order they were published."""
        return [event for event in self.events if event.name == name]

    def assert_published(
        self,
        name: str,
        *,
        count: int | None = None,
        subject: Any = _ANY,
        person: Any = _ANY,
        actor: Any = _ANY,
        version: int | None = None,
        **fields: Any,
    ) -> Event:
        """An event called ``name`` with these values (exactly ``count`` of them when given).

        Values are compared the way :func:`karni.events.publish` writes them:
        a model instance as its id, a decimal or a date as a string. Returns
        the last matching event.
        """
        from karni.outbox.bus import _key, _subject, _value

        def matches(event: Event) -> bool:
            if version is not None and event.version != version:
                return False
            if subject is not _ANY and dict(event.subject or {}) != (_subject(subject) or {}):
                return False
            if person is not _ANY and event.person != _key(person, "person"):
                return False
            if actor is not _ANY and event.actor != _key(actor, "actor"):
                return False
            return all(
                key in event.data and event.data[key] == _value(value, key)
                for key, value in fields.items()
            )

        found = [event for event in self.named(name) if matches(event)]
        if not found or (count is not None and len(found) != count):
            expected = f"{count} x " if count is not None else ""
            raise KarniAssertionError(
                f"expected {expected}{name!r} with {fields or 'any fields'}, found "
                f"{len(found)}. {_show(self.events)}. (assert_not_published checks for none.)",
                code="E456",
            )
        return found[-1]

    def assert_not_published(self, name: str) -> None:
        """No event called ``name`` was published."""
        found = self.named(name)
        if found:
            raise KarniAssertionError(
                f"expected no {name!r}, found {len(found)}. {_show(found)}.", code="E456"
            )


@contextmanager
def capture_events() -> Iterator[PublishedEvents]:
    """Collect every family event published inside the block."""
    from karni.outbox.bus import capturing

    with capturing() as found:
        yield PublishedEvents(found)


def deliver_now(*, event: Event | str | None = None, using: str | None = None) -> Any:
    """Run every pending delivery now (or those of ``event``), backoff ignored.

    Each pending delivery runs once per call. Events its subscribers publish
    are delivered in the same call. Returns the
    :class:`~karni.outbox.delivery.DeliveryReport` of the whole run.
    """
    from karni.outbox.delivery import DeliveryReport, deliver_event, require_outbox

    require_outbox("deliver_now()")
    from karni.outbox.models import Delivery

    report = DeliveryReport()
    seen: set[str] = set()
    if event is not None:
        queue = [event.id if isinstance(event, Event) else str(event)]
    else:
        queue = _pending(Delivery, using, seen)
    while queue:
        for event_id in queue:
            seen.add(event_id)
            report.add(deliver_event(event_id, force=True, using=using))
        queue = [] if event is not None else _pending(Delivery, using, seen)
    return report


def _pending(delivery: Any, using: str | None, seen: set[str]) -> list[str]:
    rows = delivery.objects.using(using) if using else delivery.objects
    ids = (
        rows.filter(status=delivery.Status.PENDING)
        .order_by("event__occurred_at")
        .values_list("event_id", flat=True)
    )
    found: list[str] = []
    for pk in ids:
        key = str(pk)
        if key not in seen and key not in found:
            found.append(key)
    return found


def _published_names(path: Path) -> list[tuple[str, int | None, int]]:
    """``(name, version, line)`` of every ``publish("<literal>")`` call in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int | None, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        first = node.args[0]
        if name != "publish" or not (
            isinstance(first, ast.Constant) and isinstance(first.value, str)
        ):
            continue
        version: int | None = None
        for keyword in node.keywords:
            if (
                keyword.arg == "version"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, int)
            ):
                version = keyword.value.value
        found.append((first.value, version, node.lineno))
    return found


def assert_events_declared(app_label: str) -> list[str]:
    """Every ``publish("<name>")`` in the app's code names a declared event.

    Reads the app's Python files (not its tests or migrations). A name passed
    as a variable is not checked. Returns the event names the app publishes.
    """
    from django.apps import apps

    from karni.outbox.bus import registry

    root = Path(apps.get_app_config(app_label).path)
    problems: list[str] = []
    names: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        parts = set(path.relative_to(root).parts)
        if parts & {"tests", "migrations"} or path.name.startswith("test_"):
            continue
        for name, version, line in _published_names(path):
            names.add(name)
            if registry.declaration(name, version) is None:
                where = f"{path.relative_to(root.parent)}:{line}"
                asked = f" version {version}" if version is not None else ""
                problems.append(f"{where} publishes {name!r}{asked}, which nothing declares")
    if problems:
        raise KarniAssertionError(
            f"{app_label} publishes undeclared events:\n  "
            + "\n  ".join(problems)
            + "\nDeclare each in the app's events.py with karni.events.declare().",
            code="E456",
        )
    return sorted(names)
