"""Experimental. Writing the timeline: ``record()`` by hand, entries from family events, pruning.

Two writers fill the timeline:

* :func:`record`, for what is not a family event: a call a CRM logs, a note,
  a meeting. A part calls it inside its own transaction.
* :func:`write_from_event`, the core subscriber of every family event whose
  declaration names a timeline title (``declare(..., timeline="...")``). It
  runs after the publisher committed, in the delivery's transaction.

The ``timeline=`` option of a declaration is a title template, or a mapping:

``title``
    The title template (required). ``{field}`` is replaced by the event's
    declared field of that name, as text.
``body``
    A body template, the same way (optional).
``subjects``
    ``{field: "app_label.model"}``: declared fields that hold the id of
    another record the entry shows on (the event's subject always is one).
``kind``
    The entry's kind (default: the event's name).
``money``
    ``{field: currency}``: declared fields that hold an amount, each with the
    declared field that holds its currency (or a fixed ISO 4217 code). The
    title and body write the amount as plain money, ``127.54 USD`` (the
    currency's places, the code in capitals), and the entry keeps each one in
    ``data["$money"]`` (``[{"text", "amount", "currency"}]``), so a screen
    shows it as the project's money (@karni/ui's ``<Timeline>``: ``$127.54``).

:func:`skip_when` lets an app leave out the entries of an event it covers
itself: karni-commerce leaves out a payment's entry when the payment belongs
to an order, whose own entry says it was paid.

A template names declared fields only, with no attribute, index, conversion
or format spec (``karni.E460`` at startup otherwise), so a title never reads
more than the payload holds.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import string
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, models, router, transaction
from django.utils import timezone

from karni.exceptions import KarniTypeError, KarniValueError
from karni.outbox.bus import CURRENT_USER

if TYPE_CHECKING:
    from karni.outbox.bus import Declaration, Event
    from karni.timeline.models import TimelineEntry

__all__ = [
    "APP",
    "MONEY_KEY",
    "TimelineOption",
    "erase_person",
    "installed",
    "money_text",
    "parse_option",
    "prune",
    "record",
    "render",
    "retention_days",
    "skip_when",
    "skipped",
    "unskip",
    "write_from_event",
]

#: The dotted path a project adds to ``INSTALLED_APPS``.
APP: Final = "karni.timeline"
#: A kind: two or more lower-case words joined by dots (``crm.note``, ``shop.order.paid``).
KIND_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
#: The keys a ``timeline=`` mapping takes.
OPTION_KEYS: Final = frozenset({"title", "body", "subjects", "kind", "money"})
#: Where an entry keeps its amounts (``data["$money"]``): ``[{"text", "amount", "currency"}]``.
MONEY_KEY: Final = "$money"
_CURRENCY_CODE: Final = re.compile(r"^[A-Za-z]{3}$")
#: How many ``merged_into`` steps a person id is followed to the live person.
_MERGE_HOPS: Final = 10
_ELLIPSIS: Final = "..."


def installed() -> bool:
    """Experimental. Whether ``karni.timeline`` is in ``INSTALLED_APPS``."""
    return apps.is_installed(APP)


# the timeline= option --------------------------------------------------------------------


@dataclass(frozen=True)
class TimelineOption:
    """Experimental. A declaration's ``timeline=`` option, checked: what its entries say."""

    title: str
    body: str = ""
    subjects: Mapping[str, str] = field(default_factory=dict)
    kind: str = ""
    money: Mapping[str, str] = field(default_factory=dict)


def _placeholders(template: str, where: str) -> list[str]:
    """The field names ``template`` uses. E460 for anything but a plain ``{name}``."""
    names: list[str] = []
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise KarniValueError(
            f"karni.timeline: {where} {template!r} is not a valid template ({exc}). Write "
            "plain text with {field} for a declared field, and {{ or }} for a brace.",
            code="E460",
        ) from exc
    for _text, name, spec, conversion in parsed:
        if name is None:
            continue
        if not re.match(r"^[a-z][a-z0-9_]*$", name) or spec or conversion:
            raise KarniValueError(
                f"karni.timeline: {where} {template!r} uses {{{name}"
                f"{'!' + conversion if conversion else ''}{':' + spec if spec else ''}}}. "
                "A template takes a declared field by its plain name, {field}, with no "
                "attribute, index, conversion or format.",
                code="E460",
            )
        names.append(name)
    return names


def parse_option(declaration: Declaration) -> TimelineOption | None:
    """Experimental. ``declaration.timeline`` checked against its fields, or None when unset.

    :raises KarniValueError: E460, the option is malformed or names a field
        the event does not declare.
    """
    raw = declaration.timeline
    if raw is None:
        return None
    name = f"{declaration.name} v{declaration.version}"
    if isinstance(raw, str):
        option = TimelineOption(title=raw)
    elif isinstance(raw, Mapping):
        unknown = sorted(set(raw) - OPTION_KEYS)
        if unknown:
            raise KarniValueError(
                f"karni.timeline: {name} has timeline keys {', '.join(map(str, unknown))}. "
                f"The keys are {', '.join(sorted(OPTION_KEYS))}.",
                code="E460",
            )
        subjects = raw.get("subjects") or {}
        if not isinstance(subjects, Mapping):
            raise KarniValueError(
                f"karni.timeline: {name} has timeline subjects {subjects!r}. Pass "
                '{"field": "app_label.model"}: the declared field holding the id of a record '
                "the entry also shows on.",
                code="E460",
            )
        money = raw.get("money") or {}
        if not isinstance(money, Mapping):
            raise KarniValueError(
                f"karni.timeline: {name} has timeline money {money!r}. Pass "
                '{"amount": "currency"}: a declared field with an amount, and the declared '
                "field (or the ISO 4217 code) of its currency.",
                code="E460",
            )
        option = TimelineOption(
            title=raw.get("title", ""),
            body=raw.get("body", "") or "",
            subjects=dict(subjects),
            kind=raw.get("kind", "") or "",
            money={str(key): str(value) for key, value in money.items()},
        )
    else:
        raise KarniTypeError(
            f"karni.timeline: {name} has timeline={raw!r}: pass a title template or a mapping.",
            code="E460",
        )
    if not isinstance(option.title, str) or not option.title.strip():
        raise KarniValueError(
            f"karni.timeline: {name} has no timeline title. Write one, for example "
            'timeline="Ticket {ticket} closed".',
            code="E460",
        )
    if not isinstance(option.body, str):
        raise KarniTypeError(
            f"karni.timeline: {name} has timeline body {option.body!r}: write a template.",
            code="E460",
        )
    used = _placeholders(option.title, f"{name}'s timeline title") + _placeholders(
        option.body, f"{name}'s timeline body"
    )
    missing = sorted({field_name for field_name in used if field_name not in declaration.fields})
    if missing:
        raise KarniValueError(
            f"karni.timeline: {name}'s timeline names {', '.join(missing)}, which the event "
            f"does not declare. Its fields: {', '.join(declaration.fields) or 'none'}.",
            code="E460",
        )
    for field_name, label in option.subjects.items():
        if field_name not in declaration.fields:
            raise KarniValueError(
                f"karni.timeline: {name}'s timeline subject {field_name!r} is not a declared "
                f"field. Its fields: {', '.join(declaration.fields) or 'none'}.",
                code="E460",
            )
        try:
            apps.get_model(str(label))
        except (LookupError, ValueError) as exc:
            raise KarniValueError(
                f"karni.timeline: {name}'s timeline subject {field_name!r} names the model "
                f"{label!r}, which is not installed. Name it as 'app_label.model'.",
                code="E460",
            ) from exc
    for field_name, currency in option.money.items():
        if field_name not in declaration.fields or not (
            currency in declaration.fields or _CURRENCY_CODE.match(currency)
        ):
            raise KarniValueError(
                f"karni.timeline: {name}'s timeline money {field_name!r}: {currency!r} names "
                "an amount the event does not declare, or a currency that is neither a declared "
                f"field nor an ISO 4217 code. Its fields: {', '.join(declaration.fields)}.",
                code="E460",
            )
    if option.kind and not KIND_PATTERN.match(option.kind):
        raise KarniValueError(
            f"karni.timeline: {name}'s timeline kind {option.kind!r} is not a kind. A kind is "
            "lower-case words joined by dots: 'crm.note', 'helpdesk.ticket.closed'.",
            code="E460",
        )
    return option


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True)


def render(template: str, values: Mapping[str, Any]) -> str:
    """Experimental. ``template`` with each ``{field}`` replaced by ``values[field]`` as text.

    A missing or null value is empty. Only plain names are read (E460 for
    anything else).
    """
    _placeholders(template, "the template")
    found = {key: _text(value) for key, value in values.items()}
    out: list[str] = []
    for text, name, _spec, _conversion in string.Formatter().parse(template):
        out.append(text)
        if name is not None:
            out.append(found.get(name, ""))
    return "".join(out).strip()


def money_text(amount: Any, currency: Any) -> tuple[str, str, str] | None:
    """Experimental. ``(text, amount, CODE)``: ``("127.54 USD", "127.54", "USD")``.

    The amount at the currency's places (ISO 4217), the code in capitals.
    ``None`` when the amount is not a number or the currency not a code.
    """
    from decimal import Decimal, InvalidOperation

    from karni.fields.iso_data import MINOR_UNITS

    code = str(currency or "").upper()
    if not _CURRENCY_CODE.match(code):
        return None
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    places = MINOR_UNITS.get(code, 2)
    shown = value.quantize(Decimal(1).scaleb(-(2 if places is None else places)))
    return f"{shown} {code}", str(shown), code


def _money_values(
    option: TimelineOption, values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The values the templates read, each money field as plain money, and the amounts."""
    shown = dict(values)
    amounts: list[dict[str, str]] = []
    for field_name, currency in option.money.items():
        code = values.get(currency) if currency in values else currency
        found = money_text(values.get(field_name), code)
        if found is None:
            continue
        text, amount, upper = found
        shown[field_name] = text
        amounts.append({"text": text, "amount": amount, "currency": upper})
    return shown, amounts


#: Event name -> the checks an app registered: an event a check answers True for writes no entry.
_SKIPS: dict[str, list[Any]] = {}


def skip_when(name: str, check: Any) -> None:
    """Experimental. Leave out the timeline entry of ``name`` for an event ``check(event)`` is
    true for: an app that covers that moment with an entry of its own.

    karni-commerce leaves out ``payments.payment.succeeded`` for a payment of
    an order. A check that raises leaves the entry in.
    """
    _SKIPS.setdefault(name, []).append(check)


def unskip(name: str, check: Any = None) -> None:
    """Experimental. Take back a :func:`skip_when` check (every check of ``name`` without one)."""
    if check is None:
        _SKIPS.pop(name, None)
    elif check in _SKIPS.get(name, []):
        _SKIPS[name].remove(check)


def skipped(event: Event) -> bool:
    """Experimental. Whether an app's :func:`skip_when` check leaves ``event``'s entry out."""
    for check in _SKIPS.get(event.name, []):
        try:
            if check(event):
                return True
        except Exception:  # noqa: BLE001 - a broken check never hides a moment
            continue
    return False


def _title(text: str) -> str:
    from karni.timeline.models import TITLE_LENGTH

    clean = " ".join(str(text).split())
    if len(clean) <= TITLE_LENGTH:
        return clean
    return clean[: TITLE_LENGTH - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


# record ------------------------------------------------------------------------------------


def _ref(subject: Any, where: str) -> tuple[type[models.Model], str]:
    """``(model, str(pk))`` of a model instance or an ``("app_label.model", id)`` pair."""
    if isinstance(subject, models.Model):
        if subject.pk is None:
            raise KarniValueError(
                f"karni.timeline: {where} is an unsaved {type(subject).__name__}. Save it first.",
                code="E462",
            )
        return type(subject), str(subject.pk)
    if (
        isinstance(subject, tuple)
        and len(subject) == 2
        and isinstance(subject[0], str)
        and subject[1] is not None
    ):
        try:
            model = apps.get_model(subject[0])
        except (LookupError, ValueError) as exc:
            raise KarniValueError(
                f"karni.timeline: {where} names {subject[0]!r}, which is not an installed "
                "model. Name it as 'app_label.model'.",
                code="E462",
            ) from exc
        return model, clean_id(model, subject[1], where)
    raise KarniTypeError(
        f"karni.timeline: {where} is {subject!r}. Pass a model instance or a pair "
        "('app_label.model', id).",
        code="E462",
    )


def clean_id(model: type[models.Model], value: Any, where: str) -> str:
    """``value`` as ``model``'s primary key, as text (E462 when it cannot be one)."""
    try:
        cleaned = model._meta.pk.to_python(value)  # type: ignore[union-attr]
    except (ValidationError, TypeError, ValueError) as exc:
        raise KarniValueError(
            f"karni.timeline: {where} has the id {value!r}, which is not a key of "
            f"{model._meta.label}.",
            code="E462",
        ) from exc
    if cleaned is None or cleaned == "":
        raise KarniValueError(f"karni.timeline: {where} has no id.", code="E462")
    return str(cleaned)


def _person_id(person: Any) -> Any:
    """The person's key, or None. A Person instance, its id, or None."""
    if person is None:
        return None
    from karni.people.models import Person

    if isinstance(person, models.Model):
        if not isinstance(person, Person):
            raise KarniTypeError(
                f"karni.timeline: person= is a {type(person).__name__}. Pass a "
                "people.Person (or its id), and other records as subjects=.",
                code="E462",
            )
        return person.pk
    return clean_id(Person, person, "person=")


def _actor_id(actor: Any) -> Any:
    from django.contrib.auth import get_user_model

    if actor is CURRENT_USER:
        from karni.middleware import get_current_user

        actor = get_current_user()
    if actor is None:
        return None
    if isinstance(actor, models.Model):
        return actor.pk if getattr(actor, "is_authenticated", True) else None
    user_model = get_user_model()
    try:
        return user_model._meta.pk.to_python(actor)  # type: ignore[union-attr]
    except (ValidationError, TypeError, ValueError) as exc:
        raise KarniValueError(
            f"karni.timeline: actor={actor!r} is not a user or a user's id.", code="E462"
        ) from exc


def _data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise KarniTypeError(
            f"karni.timeline: data={data!r}. Pass a mapping of JSON values.", code="E462"
        )
    try:
        loaded = json.loads(json.dumps(dict(data), cls=DjangoJSONEncoder))
    except (TypeError, ValueError) as exc:
        raise KarniTypeError(
            f"karni.timeline: data holds a value that is not JSON ({exc}). Pass ids and "
            "values: a model instance as its id.",
            code="E462",
        ) from exc
    return dict(loaded)


def record(
    *,
    kind: str,
    title: str,
    person: Any = None,
    subjects: Iterable[Any] = (),
    body: str = "",
    occurred_at: dt.datetime | None = None,
    actor: Any = CURRENT_USER,
    source: str | None = None,
    data: Mapping[str, Any] | None = None,
    event_id: str | uuid.UUID | None = None,
    using: str | None = None,
) -> TimelineEntry | None:
    """Experimental. Write one entry on the timeline of ``person`` and of each subject.

    For what is not a family event: a call a CRM logs, a note, a meeting.
    Call it inside the transaction of the change it reports. Returns the
    entry, or ``None`` when ``karni.timeline`` is not installed, so a part
    calls it whether or not the project keeps a timeline.

    :param kind: what happened, lower-case words joined by dots
        (``"crm.call"``). The first word is the part.
    :param title: one line of plain text, written now (cut at 300
        characters).
    :param person: the person it is about (a ``people.Person`` or its id).
    :param subjects: the other records it shows on: model instances or
        ``("app_label.model", id)`` pairs.
    :param body: more text (optional).
    :param occurred_at: when it happened (default: now).
    :param actor: the user who acted, or their id, or ``None`` (default:
        the current request's user, none outside a request).
    :param source: the part that wrote it (default: the first word of
        ``kind``).
    :param data: JSON values to keep with the entry.
    :param event_id: the family event it reports. With an id, a second
        call for the same event and person returns the first entry.
    :raises KarniValueError: E462, an argument is not usable.
    """
    if not installed():
        return None
    from karni.timeline.models import TimelineEntry, TimelineLink

    if not isinstance(kind, str) or not KIND_PATTERN.match(kind):
        raise KarniValueError(
            f"karni.timeline: record(kind={kind!r}). A kind is lower-case words joined by "
            "dots, the part first: 'crm.call', 'helpdesk.note'.",
            code="E462",
        )
    if not isinstance(title, str) or not title.strip():
        raise KarniValueError(
            "karni.timeline: record() needs a title, one line of plain text.", code="E462"
        )
    if not isinstance(body, str):
        raise KarniTypeError(f"karni.timeline: record(body={body!r}) takes text.", code="E462")
    if isinstance(subjects, str | bytes | models.Model) or (
        isinstance(subjects, tuple) and len(subjects) == 2 and isinstance(subjects[0], str)
    ):
        raise KarniTypeError(
            f"karni.timeline: record(subjects={subjects!r}) takes a list of records.",
            code="E462",
        )
    person_id = _person_id(person)
    refs: list[tuple[type[models.Model], str]] = []
    for index, subject in enumerate(subjects):
        ref = _ref(subject, f"subjects[{index}]")
        if ref not in refs:
            refs.append(ref)
    if person_id is None and not refs:
        raise KarniValueError(
            "karni.timeline: record() names neither a person nor a subject, so the entry would "
            "show on no timeline. Pass person= or subjects=.",
            code="E462",
        )
    alias = using or router.db_for_write(TimelineEntry)
    try:
        event_key = str(uuid.UUID(str(event_id))) if event_id is not None else None
    except ValueError as exc:
        raise KarniValueError(
            f"karni.timeline: record(event_id={event_id!r}) takes a family event's id, a UUID.",
            code="E462",
        ) from exc
    if event_key is not None:
        found = _existing(alias, event_key, person_id)
        if found is not None:
            return found
    entry = TimelineEntry(
        occurred_at=occurred_at or timezone.now(),
        kind=kind,
        title=_title(title),
        body=body,
        actor_id=_actor_id(actor),
        person_id=person_id,
        source=(source if source is not None else kind.split(".", 1)[0])[:64],
        event_id=event_key,
        data=_data(data),
    )
    from django.contrib.contenttypes.models import ContentType

    try:
        with transaction.atomic(using=alias):
            entry.save(using=alias, force_insert=True)
            TimelineLink.objects.using(alias).bulk_create(
                [
                    TimelineLink(
                        entry=entry,
                        content_type=ContentType.objects.db_manager(alias).get_for_model(
                            model, for_concrete_model=False
                        ),
                        object_id=object_id,
                    )
                    for model, object_id in refs
                ]
            )
    except IntegrityError:
        if event_key is None:
            raise
        found = _existing(alias, event_key, person_id)
        if found is None:
            raise
        return found
    return entry


def _existing(alias: str, event_key: str, person_id: Any) -> TimelineEntry | None:
    from karni.timeline.models import TimelineEntry

    rows = TimelineEntry.objects.using(alias).filter(event_id=event_key)
    rows = rows.filter(person_id=person_id) if person_id is not None else rows.filter(person=None)
    return rows.first()


# entries from family events ----------------------------------------------------------------


def live_person(person_id: Any, *, using: str | None = None) -> Any:
    """The key of the live person ``person_id`` is or was merged into, or None.

    A person merged into another one is followed to the person that stayed,
    so an event published before a merge still lands on the right timeline.
    An unknown or erased person is None.
    """
    if person_id in (None, ""):
        return None
    from karni.people.models import Person

    try:
        key = Person._meta.pk.to_python(person_id)  # type: ignore[union-attr]
    except (ValidationError, TypeError, ValueError):
        return None
    manager = Person._base_manager.using(using) if using else Person._base_manager
    for _hop in range(_MERGE_HOPS):
        row = manager.filter(pk=key).values("pk", "merged_into_id", "deleted_at").first()
        if row is None:
            return None
        if row["merged_into_id"] is None:
            return row["pk"] if row["deleted_at"] is None else None
        key = row["merged_into_id"]
    return None


def write_from_event(event: Event, declaration: Declaration) -> TimelineEntry | None:
    """Experimental. The entry ``event`` writes, as its declaration's ``timeline=`` says.

    Written on the timeline of the event's person (followed through merges)
    and its subject, and of each record ``subjects`` names. An event with
    neither a known person nor a subject writes nothing. A redelivered event
    returns the entry it wrote the first time.
    """
    option = parse_option(declaration)
    if option is None or skipped(event):
        return None
    values = dict(event.data)
    shown, amounts = _money_values(option, values)
    subjects: list[Any] = []
    if event.subject and event.subject.get("model") and event.subject.get("id"):
        subjects.append((str(event.subject["model"]), event.subject["id"]))
    for field_name, label in option.subjects.items():
        value = values.get(field_name)
        if value not in (None, ""):
            subjects.append((label, value))
    person = live_person(event.person)
    refs: list[Any] = []
    for subject in subjects:
        try:
            refs.append(_ref(subject, f"{event.name}'s subject"))
        except (KarniValueError, KarniTypeError):
            continue  # a record of a model that is gone, or an id that is not a key
    if person is None and not refs:
        return None
    return record(
        kind=option.kind or event.name,
        title=render(option.title, shown),
        body=render(option.body, shown) if option.body else "",
        person=person,
        subjects=[(model._meta.label_lower, key) for model, key in refs],
        occurred_at=event.occurred_at,
        actor=_existing_user(event.actor),
        source=declaration.prefix,
        data={**values, MONEY_KEY: amounts} if amounts else values,
        event_id=event.id,
    )


def _existing_user(actor_id: Any) -> Any:
    """``actor_id`` when that user still exists, else None (the entry keeps no dangling actor)."""
    if actor_id in (None, ""):
        return None
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    try:
        key = user_model._meta.pk.to_python(actor_id)  # type: ignore[union-attr]
    except (ValidationError, TypeError, ValueError):
        return None
    return key if user_model._base_manager.filter(pk=key).exists() else None


# retention and erase -------------------------------------------------------------------------


def retention_days() -> int | None:
    """``KARNI_TIMELINE_RETENTION_DAYS``: days an entry is kept, None for ever (the default)."""
    from django.conf import settings

    value = getattr(settings, "KARNI_TIMELINE_RETENTION_DAYS", None)
    return None if value is None else int(value)


def prune(
    days: int | None = None, *, kinds: Iterable[str] | None = None, using: str | None = None
) -> int:
    """Experimental. Delete entries older than ``days`` (``KARNI_TIMELINE_RETENTION_DAYS``).

    ``kinds`` limits it to those kinds. Returns the number of entries
    deleted, 0 while retention is ``None``.
    """
    from karni.timeline.models import TimelineEntry

    window = days if days is not None else retention_days()
    if window is None:
        return 0
    alias = using or router.db_for_write(TimelineEntry)
    cutoff = timezone.now() - dt.timedelta(days=int(window))
    old = TimelineEntry.objects.using(alias).filter(occurred_at__lt=cutoff)
    if kinds is not None:
        old = old.filter(kind__in=list(kinds))
    _, deleted = old.delete()
    return int(deleted.get(TimelineEntry._meta.label, 0))


def erase_person(person: Any) -> None:
    """The people contract's erase hook: a person's entries go, with the links to them.

    Entries are about the person and their titles were written with their
    details, so an erase deletes every entry whose person they are and every
    entry linked to them.
    """
    from django.contrib.contenttypes.models import ContentType

    from karni.timeline.models import TimelineEntry, TimelineLink

    content_type = ContentType.objects.get_for_model(type(person), for_concrete_model=False)
    linked = TimelineLink.objects.filter(content_type=content_type, object_id=str(person.pk))
    TimelineEntry.objects.filter(pk__in=linked.values("entry_id")).delete()
    TimelineEntry.objects.filter(person=person).delete()
