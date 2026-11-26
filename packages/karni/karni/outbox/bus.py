"""The family event bus: declare, publish and subscribe by name.

Imported through :mod:`karni.events`, which re-exports every public name
here. A publisher declares its events in ``<app>/events.py``::

    from karni.events import declare

    declare(
        "desk.ticket.closed",
        version=1,
        fields={"ticket": "the ticket's id", "minutes": "time to close, a whole number"},
        person="person",
        describe="A ticket was closed by staff.",
    )

and publishes inside the transaction that made the change::

    from karni.events import publish

    with transaction.atomic():
        ticket.close()
        publish("desk.ticket.closed", subject=ticket, person=ticket.requester_id,
                ticket=str(ticket.pk), minutes=ticket.minutes_open)

A subscriber in another app's ``listeners.py`` names the event and never
imports the publisher::

    from karni.events import Event, subscribe


    @subscribe("desk.ticket.closed", version=1)
    def thank_requester(event: Event) -> None:
        ...  # event["ticket"], event.person, event.id

When the publisher's app is not installed, the event is never declared or
published, so the subscriber is never called and nothing fails.

Names are ``<prefix>.<record>.<moment>``, lower case, the moment in the past
tense. The payload always carries ``id`` (the event's own id), ``name``,
``version``, ``occurred_at``, ``actor`` (a user id or null), ``person`` (a
person id or null), ``subject`` (``{"model": "app.model", "id": "..."}`` or
null) and ``request_id``, then the declared fields: ids, states and amounts
as plain JSON values. Decimals, UUIDs and dates are written as strings. A
model instance is refused: pass its id.

Override / escape hatches: :class:`Registry` is a plain class (pass your own
to :func:`declare`, :func:`subscribe` and :func:`publish` with
``registry=``), a subscriber's ``name=`` keeps its deliveries when the
function moves, and plain Django signals keep working for a part's own rules
inside its own transaction.
"""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import re
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, TypeVar

from django.db import models

from karni.exceptions import (
    KarniImproperlyConfigured,
    KarniLookupError,
    KarniTypeError,
    KarniValueError,
)

__all__ = [
    "COMMON_FIELDS",
    "CONTRACT",
    "Declaration",
    "Event",
    "Registry",
    "Subscriber",
    "build",
    "declare",
    "once",
    "publish",
    "registry",
    "subscribe",
]

#: The version of the family events contract. A part names the range it
#: needs, and a breaking change raises it.
CONTRACT: Final = 1

#: ``<prefix>.<record>.<moment>``: lower case words joined by underscores.
NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
#: A declared field name.
FIELD_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$")
#: What every payload carries, before the declared fields.
COMMON_FIELDS: Final = (
    "id",
    "name",
    "version",
    "occurred_at",
    "actor",
    "person",
    "subject",
    "request_id",
)

F = TypeVar("F", bound=Callable[..., Any])


class _Current:
    """The default of ``actor=``: the current user, read when the event is built."""

    def __repr__(self) -> str:
        return "<the current user>"


CURRENT_USER: Final = _Current()
_MAX_VERSION: Final = 32767


@dataclass(frozen=True)
class Declaration:
    """One declared event: its name, version and payload fields.

    ``fields`` maps each declared field to what it holds. ``person`` names
    where the person the event is about comes from: ``"person"`` (the
    ``person=`` argument of :func:`publish`), a declared field, or ``None``
    when a person is optional. ``timeline`` is kept for the timeline contract
    (a title template, or a mapping of its options), and ``describe`` says in
    one line when the event happens. ``source`` is the declaring module.
    """

    name: str
    version: int
    fields: Mapping[str, str]
    person: str | None = None
    timeline: Any = None
    describe: str = ""
    source: str = ""

    @property
    def prefix(self) -> str:
        """The part or module the event belongs to: the first word of its name."""
        return self.name.split(".", 1)[0]


@dataclass(frozen=True)
class Subscriber:
    """One subscriber: the event and version it hears, its name and function.

    ``name`` identifies its deliveries in the outbox, so it must not change
    while events wait for it: the function's dotted path by default, or the
    ``name=`` given to :func:`subscribe`.
    """

    event: str
    version: int
    name: str
    func: Callable[[Event], Any]
    source: str = ""


@dataclass(frozen=True)
class Event:
    """A published event, as a subscriber receives it.

    The common fields are attributes, the declared fields are read with
    ``event["field"]`` (or :meth:`get`). :attr:`payload` is the JSON stored in
    the outbox. Use :attr:`id` to stay idempotent: delivery is at least once.
    """

    id: str
    name: str
    version: int
    occurred_at: dt.datetime
    actor: str | None
    person: str | None
    subject: Mapping[str, str] | None
    request_id: str | None
    data: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        """A declared field, or ``default`` when the payload has none by that name."""
        return self.data.get(key, default)

    @property
    def subject_ref(self) -> str | None:
        """``"app_label.model:id"`` of the subject, or ``None``."""
        if not self.subject:
            return None
        return f"{self.subject.get('model')}:{self.subject.get('id')}"

    @property
    def payload(self) -> dict[str, Any]:
        """The event as JSON values: the common fields, then the declared ones."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor,
            "person": self.person,
            "subject": dict(self.subject) if self.subject is not None else None,
            "request_id": self.request_id,
            **self.data,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Event:
        """Rebuild an event from its stored payload (what the worker delivers)."""
        data = {key: value for key, value in payload.items() if key not in COMMON_FIELDS}
        subject = payload.get("subject")
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            version=int(payload["version"]),
            occurred_at=dt.datetime.fromisoformat(str(payload["occurred_at"])),
            actor=payload.get("actor"),
            person=payload.get("person"),
            subject=MappingProxyType(dict(subject)) if subject is not None else None,
            request_id=payload.get("request_id"),
            data=MappingProxyType(data),
        )


class Registry:
    """The declared events and the subscribers of one process.

    Filled at startup by every app's ``events.py`` and ``listeners.py``
    (:func:`karni.events.autodiscover`). A declaration or subscriber made
    again by the same module replaces the first one (a module reloaded in a
    shell or a test). The same name from two modules is refused.
    """

    def __init__(self) -> None:
        self._declarations: dict[str, dict[int, Declaration]] = {}
        self._subscribers: dict[str, Subscriber] = {}

    def add_declaration(self, declaration: Declaration) -> None:
        """Record ``declaration``. E452 when another module declared the same name and version."""
        versions = self._declarations.setdefault(declaration.name, {})
        existing = versions.get(declaration.version)
        if existing is not None and existing.source != declaration.source:
            raise KarniImproperlyConfigured(
                f"karni.events: {declaration.name!r} version {declaration.version} is declared "
                f"twice, in {existing.source} and in {declaration.source}. One part owns an "
                "event: keep one declaration, or give the new shape the next version.",
                code="E452",
            )
        versions[declaration.version] = declaration

    def declaration(self, name: str, version: int | None = None) -> Declaration | None:
        """The declaration of ``name`` at ``version``, the latest one when ``version`` is None."""
        versions = self._declarations.get(name)
        if not versions:
            return None
        if version is None:
            return versions[max(versions)]
        return versions.get(version)

    def versions(self, name: str) -> list[int]:
        """The declared versions of ``name``, oldest first."""
        return sorted(self._declarations.get(name, {}))

    def declarations(self) -> list[Declaration]:
        """Every declaration, by name and version."""
        return [
            versions[version]
            for _name, versions in sorted(self._declarations.items())
            for version in sorted(versions)
        ]

    def add_subscriber(self, subscriber: Subscriber) -> None:
        """Record ``subscriber``. E454 when another module uses the same name."""
        existing = self._subscribers.get(subscriber.name)
        if existing is not None and existing.source != subscriber.source:
            raise KarniImproperlyConfigured(
                f"karni.events: two subscribers are named {subscriber.name!r} ({existing.source} "
                f"and {subscriber.source}). A delivery finds its subscriber by name: pass a "
                "distinct name= to one of them.",
                code="E454",
            )
        self._subscribers[subscriber.name] = subscriber

    def remove_subscriber(self, name: str) -> Subscriber | None:
        """Forget the subscriber called ``name`` (a test that subscribed for itself)."""
        return self._subscribers.pop(name, None)

    def subscriber(self, name: str) -> Subscriber | None:
        """The subscriber called ``name``, as a delivery row names it."""
        return self._subscribers.get(name)

    def subscribers_of(self, name: str, version: int) -> list[Subscriber]:
        """The subscribers of ``name`` at ``version``, by name."""
        return sorted(
            (s for s in self._subscribers.values() if s.event == name and s.version == version),
            key=lambda s: s.name,
        )

    def subscribers(self) -> list[Subscriber]:
        """Every subscriber, by event, version and name."""
        return sorted(self._subscribers.values(), key=lambda s: (s.event, s.version, s.name))


#: The registry :func:`declare`, :func:`subscribe` and :func:`publish` use by default.
registry = Registry()


def _caller_module() -> str:
    """The module that called the public function calling this one."""
    return str(sys._getframe(2).f_globals.get("__name__", "?"))


def _check_name(name: Any, code: str, what: str) -> str:
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise KarniValueError(
            f"karni.events: {what} got {name!r}, which is not an event name. Names are "
            "<prefix>.<record>.<moment> in lower case, the moment in the past tense: "
            "'shop.order.paid', 'desk.ticket.closed'.",
            code=code,
        )
    return name


def _check_version(version: Any, code: str, name: str) -> int:
    whole = isinstance(version, int) and not isinstance(version, bool)
    if not whole or not 1 <= version <= _MAX_VERSION:
        raise KarniValueError(
            f"karni.events: {name!r} has version {version!r}. A version is a whole number "
            "from 1: start at 1, and declare the next number next to the old one when the "
            "payload changes shape.",
            code=code,
        )
    return version


def _check_fields(name: str, fields: Any) -> dict[str, str]:
    if isinstance(fields, str) or not isinstance(fields, Mapping | Sequence):
        raise KarniTypeError(
            f"karni.events: declare({name!r}) takes fields as {{name: description}} or a list "
            f"of names, got {fields!r}.",
            code="E452",
        )
    named = dict(fields) if isinstance(fields, Mapping) else dict.fromkeys(fields, "")
    for field_name, description in named.items():
        if not isinstance(field_name, str) or not FIELD_PATTERN.match(field_name):
            raise KarniValueError(
                f"karni.events: {name!r} declares the field {field_name!r}. Field names are "
                "lower case words joined by underscores.",
                code="E452",
            )
        if field_name in COMMON_FIELDS:
            raise KarniValueError(
                f"karni.events: {name!r} declares the field {field_name!r}, which every payload "
                f"already carries ({', '.join(COMMON_FIELDS)}). Pass it as publish()'s "
                "argument instead, or name the field differently.",
                code="E452",
            )
        if not isinstance(description, str):
            raise KarniTypeError(
                f"karni.events: {name!r} describes {field_name!r} with {description!r}: "
                "write a sentence (a string).",
                code="E452",
            )
    return named


def declare(
    name: str,
    *,
    version: int = 1,
    fields: Mapping[str, str] | Sequence[str] = (),
    person: str | None = None,
    timeline: Any = None,
    describe: str = "",
    registry: Registry | None = None,
) -> Declaration:
    """Declare a family event, in the publishing app's ``events.py``.

    :param name: ``<prefix>.<record>.<moment>``, for example ``"shop.order.paid"``.
    :param version: the payload's shape, from 1. Declare version 2 next to 1
        when the shape changes, and publish both while subscribers move.
    :param fields: the payload's own fields, ``{name: what it holds}`` (or
        the names alone). Every one must be passed to :func:`publish`.
    :param person: where the person the event is about comes from:
        ``"person"`` (``publish(person=...)``) or a declared field. Set, a
        publish without a person is refused.
    :param timeline: kept for the timeline contract: a title template or a
        mapping of its options. Not read by the bus.
    :param describe: one line saying when the event happens (``karni check``
        and the docs show it).
    :returns: the :class:`Declaration`.
    :raises KarniValueError: E452 for a malformed declaration.
    """
    _check_name(name, "E452", "declare()")
    _check_version(version, "E452", name)
    named = _check_fields(name, fields)
    if person is not None and person != "person" and person not in named:
        raise KarniValueError(
            f"karni.events: {name!r} takes the person from {person!r}, which is neither "
            "'person' (publish's person= argument) nor one of its declared fields "
            f"({', '.join(named) or 'none'}).",
            code="E452",
        )
    if timeline is not None and not isinstance(timeline, str | Mapping):
        raise KarniTypeError(
            f"karni.events: {name!r} has timeline={timeline!r}: pass a title template (a "
            "string), a mapping of the timeline's options, or None.",
            code="E452",
        )
    declaration = Declaration(
        name=name,
        version=version,
        fields=MappingProxyType(named),
        person=person,
        timeline=timeline,
        describe=str(describe or ""),
        source=_caller_module(),
    )
    (registry if registry is not None else _default()).add_declaration(declaration)
    return declaration


def _default() -> Registry:
    return registry


def _subscriber_name(func: Callable[..., Any], name: str | None) -> str:
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise KarniValueError(
                f"karni.events: subscribe(name={name!r}) needs a non-empty string.",
                code="E454",
            )
        return name
    module = getattr(func, "__module__", None)
    qualname = getattr(func, "__qualname__", None)
    if not module or not qualname or "<" in qualname:
        raise KarniImproperlyConfigured(
            f"karni.events: the subscriber {func!r} has no stable name. A delivery finds its "
            "subscriber by name in every process: define the function at the top level of "
            "<app>/listeners.py, or pass name='<app>.<what it does>'.",
            code="E454",
        )
    return f"{module}.{qualname}"


def subscribe(
    event: str,
    *,
    version: int = 1,
    name: str | None = None,
    registry: Registry | None = None,
) -> Callable[[F], F]:
    """Run the decorated ``subscriber(event)`` for each ``event`` published.

    Put subscribers in ``<app>/listeners.py``. Name the event as a string and
    never import its publisher: when the publisher is not installed, the
    subscriber is simply never called. Each delivery runs after the publisher
    committed, in its own transaction: raising rolls back the subscriber's
    writes only, and the delivery is retried with backoff.

    :param event: the event's name.
    :param version: the payload version this subscriber reads.
    :param name: the subscriber's name in the outbox (default: the
        function's dotted path). Keep it when the function moves.
    :returns: a decorator returning the function unchanged.
    """
    _check_name(event, "E454", "subscribe()")
    _check_version(version, "E454", event)
    target = registry if registry is not None else _default()
    source = _caller_module()

    def decorate(func: F) -> F:
        if not callable(func):
            raise KarniTypeError(
                f"karni.events: subscribe({event!r}) decorates a function, got {func!r}.",
                code="E454",
            )
        target.add_subscriber(
            Subscriber(
                event=event,
                version=version,
                name=_subscriber_name(func, name),
                func=func,
                source=source,
            )
        )
        return func

    return decorate


# publishing


def _value(value: Any, where: str) -> Any:
    """``value`` as plain JSON, or E453 naming what to pass instead."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, enum.Enum):
        return _value(value.value, where)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, models.Model):
        raise KarniTypeError(
            f"karni.events: {where} is a {type(value).__name__} instance. A payload carries "
            "ids and values only, so a subscriber never depends on another part's models: "
            "pass its id (str(obj.pk)).",
            code="E453",
        )
    if isinstance(value, Mapping):
        found: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise KarniTypeError(
                    f"karni.events: {where} has the key {key!r}. Keys of a payload are strings.",
                    code="E453",
                )
            found[key] = _value(item, f"{where}[{key!r}]")
        return found
    if isinstance(value, list | tuple):
        return [_value(item, f"{where}[{index}]") for index, item in enumerate(value)]
    raise KarniTypeError(
        f"karni.events: {where} is {value!r} ({type(value).__name__}), which is not a JSON "
        "value. Pass a string, a number, a boolean, None, a list or a dict of those "
        "(decimals, UUIDs and dates are turned into strings for you).",
        code="E453",
    )


def _key(value: Any, where: str) -> str | None:
    """An id as text: a model instance's primary key, or the value itself."""
    if value is None:
        return None
    if isinstance(value, models.Model):
        if value.pk is None:
            raise KarniValueError(
                f"karni.events: {where} is an unsaved {type(value).__name__}. Save it before "
                "publishing, so subscribers can find it.",
                code="E453",
            )
        return str(value.pk)
    if isinstance(value, bool) or not isinstance(value, str | int | uuid.UUID):
        raise KarniTypeError(
            f"karni.events: {where} is {value!r}. Pass a model instance or its id.",
            code="E453",
        )
    return str(value)


def _subject(subject: Any) -> dict[str, str] | None:
    if subject is None:
        return None
    if isinstance(subject, models.Model):
        return {"model": subject._meta.label_lower, "id": str(_key(subject, "subject"))}
    if (
        isinstance(subject, tuple)
        and len(subject) == 2
        and isinstance(subject[0], str)
        and "." in subject[0]
    ):
        return {"model": subject[0].lower(), "id": str(_key(subject[1], "the subject's id"))}
    raise KarniTypeError(
        f"karni.events: subject={subject!r}. Pass the model instance the event is about, or "
        "a pair ('app_label.model', id).",
        code="E453",
    )


def _actor(actor: Any) -> str | None:
    if actor is CURRENT_USER:
        from karni.middleware import get_current_user

        actor = get_current_user()
    return _key(actor, "actor")


#: Lists that receive every published event while :func:`capturing` is active.
_CAPTURES: list[list[Event]] = []


@contextmanager
def capturing() -> Iterator[list[Event]]:
    """Collect every event published in the block (``karni.testing.events.capture_events``)."""
    found: list[Event] = []
    _CAPTURES.append(found)
    try:
        yield found
    finally:
        _CAPTURES.remove(found)


def _undeclared(name: str, version: int | None, source: Registry) -> KarniLookupError:
    versions = source.versions(name)
    detail = (
        f"it is declared with version {', '.join(str(v) for v in versions)} only"
        if versions
        else "nothing declares it"
    )
    asked = f", version={version}" if version is not None else ""
    return KarniLookupError(
        f"karni.events: publish({name!r}{asked}): {detail}. Declare it in the publishing "
        f"app's events.py with declare({name!r}, version=..., fields={{...}}) first.",
        code="E450",
    )


def build(
    name: str,
    *,
    subject: Any = None,
    person: Any = None,
    actor: Any = CURRENT_USER,
    version: int | None = None,
    registry: Registry | None = None,
    **fields: Any,
) -> tuple[Event, Declaration]:
    """The event :func:`publish` would write, checked against its declaration.

    Nothing is written. Arguments as :func:`publish`. Returns the event and
    the declaration it matched.
    """
    from django.utils import timezone

    from karni.tracing import get_request_id

    source = registry if registry is not None else _default()
    declaration = source.declaration(name, version)
    if declaration is None:
        raise _undeclared(name, version, source)
    missing = [field for field in declaration.fields if field not in fields]
    extra = [field for field in fields if field not in declaration.fields]
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"not declared: {', '.join(extra)}")
        raise KarniValueError(
            f"karni.events: publish({name!r}) version {declaration.version}: "
            f"{', and '.join(parts)}. Pass exactly the declared fields "
            f"({', '.join(declaration.fields) or 'none'}), None for a value you do not have, "
            "or declare a new version for a new shape.",
            code="E453",
        )
    data = {field: _value(fields[field], f"{name} field {field!r}") for field in declaration.fields}
    person_id = _key(person, "person")
    if person_id is None and declaration.person not in (None, "person"):
        named = data.get(str(declaration.person))
        person_id = str(named) if named is not None else None
    if declaration.person is not None and person_id is None:
        raise KarniValueError(
            f"karni.events: publish({name!r}) names no person, and its declaration takes the "
            f"person from {declaration.person!r}. Pass person=<the person or its id>.",
            code="E453",
        )
    about = _subject(subject)
    event = Event(
        id=str(uuid.uuid4()),
        name=name,
        version=declaration.version,
        occurred_at=timezone.now(),
        actor=_actor(actor),
        person=person_id,
        subject=MappingProxyType(about) if about is not None else None,
        request_id=get_request_id(),
        data=MappingProxyType(data),
    )
    return event, declaration


def publish(
    name: str,
    *,
    subject: Any = None,
    person: Any = None,
    actor: Any = CURRENT_USER,
    version: int | None = None,
    using: str | None = None,
    registry: Registry | None = None,
    **fields: Any,
) -> Event:
    """Publish a declared event inside the caller's transaction.

    Writes one outbox row, and one delivery row per subscriber, in the
    current transaction, so the event exists exactly when the change
    committed. After the commit, ``KARNI_EVENTS_DISPATCHER`` hands it to a
    worker. A rolled-back transaction publishes nothing.

    :param name: a declared event's name.
    :param subject: the model instance the event is about (or
        ``("app_label.model", id)``).
    :param person: the person the event is about, or its id.
    :param actor: the user who acted (default: the current user, from the
        request), or its id, or ``None``.
    :param version: which declared version to publish (default: the latest).
        Publish each version while subscribers move from the old one.
    :param using: the database alias of the outbox (default: the router's).
    :param fields: the declared fields, as JSON values.
    :returns: the published :class:`Event`.
    :raises KarniLookupError: E450, the event is not declared.
    :raises KarniValueError: E453, the fields do not match the declaration.
    """
    from karni.outbox.delivery import store

    source = registry if registry is not None else _default()
    event, declaration = build(
        name,
        subject=subject,
        person=person,
        actor=actor,
        version=version,
        registry=source,
        **fields,
    )
    for captured in _CAPTURES:
        captured.append(event)
    store(event, source.subscribers_of(name, declaration.version), using=using)
    return event


def once(event: Event | str | uuid.UUID, key: str, *, using: str | None = None) -> bool:
    """True the first time ``(event, key)`` is seen, False every time after.

    For a subscriber whose work has no unique key of its own:
    ``if once(event, "welcome-email"): send()``. The mark is written in the
    current transaction, so it is undone with the work it guards when that
    transaction rolls back. Needs ``karni.outbox`` in ``INSTALLED_APPS``.
    """
    from django.db import IntegrityError, router, transaction

    from karni.outbox.delivery import require_outbox

    require_outbox("karni.events.once()")
    from karni.outbox.models import Handled

    if not isinstance(key, str) or not key or len(key) > 200:
        raise KarniValueError(
            f"karni.events.once(): key {key!r} must be a string of 1 to 200 characters.",
            code="E453",
        )
    event_id = event.id if isinstance(event, Event) else str(event)
    alias = using or router.db_for_write(Handled)
    try:
        with transaction.atomic(using=alias):
            Handled.objects.using(alias).create(event_id=event_id, key=key)
    except IntegrityError:
        return False
    return True
