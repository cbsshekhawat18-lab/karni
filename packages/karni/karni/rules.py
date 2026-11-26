"""Rules a model declares in ``class Karni`` and Karni keeps on every write.

A business rule written as hand code in each project (a price above zero, one
booking per member and slot, a lesson only in my own course, no delete while
children exist) is written once here, as data::

    class Order(BaseModel):
        class Karni:
            bounds = {"quantity": {"min": 1}}
            unique = [{"fields": ["listing", "buyer"], "where": {"status": "pending"}}]
            targets = {"listing": {"active": True, "seller__user": {"not": "$me"}}}
            frozen = {"listing": True, "quantity": True}
            delete = {"when": {"status": "pending"}, "blocked_by": ["Payout"]}
            moves = {"refunded": {"requires": ["refund_reason"], "stamps": ["refunded_at"]}}

Every option is a plain dict or list, so ``karni.yaml`` writes it unchanged
(the spec's ``bounds``, ``unique``, ``targets``, ``frozen``, ``delete`` and
``moves`` keys). The pieces they share:

* **A row filter**: ``{path: value}``, every entry must hold. ``path`` is a
  field or a path through relations (``seller__user``), optionally ending in
  one of the lookups ``gt``, ``gte``, ``lt``, ``lte``, ``in``, ``isnull``. A
  value is a literal (text, number, ``true``/``false``, a list for ``in``),
  ``$me`` (the signed-in user), ``$now``, ``$today``, ``$<path>`` (a field of
  the row being written, ``$enrolment__course``) or ``{not: <value>}``. An
  entry that names ``$me`` is left out when nobody is signed in (a task, a
  seed, the shell): a rule about the caller needs a caller.
* **A relation reference**: ``Deal`` (the one foreign key of ``Deal`` that
  points here), ``Deal.company`` (that foreign key), or ``crm.Deal`` for an
  entity of another app. Only live rows count.

What each option does, and the error a refusal carries:

* ``bounds`` (``E990``): ``{field: {min, max}}`` on numbers, dates and
  datetimes (``$now`` and ``$today`` for dates), checked when the value is
  written new or changed. A few minutes of clock difference between a
  browser and the server pass for ``$now`` (``KARNI_RULES_CLOCK_SKEW``).
* ``unique`` (``E991``): each entry is a list of fields, or ``{fields,
  where}`` with a row filter of literal values: a :class:`UniqueRule`, a
  partial unique index over live rows that PostgreSQL and SQLite enforce.
* ``targets`` (``E993``): ``{foreign key: row filter}``: the row it points at
  must match, checked when the key (or a ``$<path>`` it reads) changes.
* ``frozen`` (``E994``): ``{field: true}`` is set on create and never
  changed; ``{field: <row filter>}`` cannot change while the stored row
  matches the filter (``{"value": {"stage": "won"}}``).
* ``delete`` (``E995``, HTTP 409): ``when`` (a row filter the stored row must
  match to be deleted) and ``blocked_by`` (relation references, or a mapping
  of them to a row filter of the rows that block).
* ``moves`` (``E996``): ``{state: {requires, needs, stamps}}``. A key is a
  state of the model's one StateField, ``<field>:<state>``, or a boolean
  field (the move is to ``true``). ``requires`` lists fields that must hold
  a value after the move, ``needs`` relation references that must have a
  live row, ``stamps`` date or datetime fields set to now (unless the same
  write sets them).

Where they run: ``save()`` checks every one before any SQL (and writes the
stamps), ``clean()`` turns a refusal into a form error (the admin, imports,
``full_clean()``), ``delete()`` checks ``delete``, and the API answers 400
(409 for a delete) naming the field. ``QuerySet.update()``, ``bulk_create()``
and the bulk soft delete bypass them, as they bypass ``save()``. The unique
index holds against every write.

Override / escape hatches: override ``check_rules()`` / ``check_delete_rules()``
on the model; subclass ``class Karni`` to change one option; wrap data
loading in :func:`unchecked` (with a reason); ``karni check`` reports a
declaration that cannot work (``E998``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.constants import LOOKUP_SEP
from django.db.models.signals import class_prepared
from django.utils import timezone

from karni.conflicts import KarniConflict, Violation, same_constraint
from karni.errorcodes import KarniError
from karni.exceptions import KarniImproperlyConfigured, KarniValueError
from karni.fields.base import object_name
from karni.fields.constraints import LiveUniqueConstraint
from karni.meta import karni_option

__all__ = [
    "LOOKUPS",
    "OPTIONS",
    "Bound",
    "DeleteRefused",
    "DeleteRule",
    "Move",
    "RuleViolation",
    "Rules",
    "Unique",
    "UniqueConflict",
    "UniqueRule",
    "check_delete",
    "check_write",
    "clock",
    "clear_caches",
    "describe_filter",
    "filter_q",
    "related_rows",
    "rules_of",
    "send_move_email",
    "silent",
    "unchecked",
    "unique_conflict",
]

#: The ``class Karni`` options this module reads, in the order it checks them.
OPTIONS: Final = ("bounds", "unique", "targets", "frozen", "delete", "moves")
#: The lookups a row filter's path may end in (Django's names).
LOOKUPS: Final = frozenset({"exact", "gt", "gte", "lt", "lte", "in", "isnull"})
#: The values a row filter resolves itself (anything else after ``$`` is a path on the row).
ME: Final = "$me"
NOW: Final = "$now"
TODAY: Final = "$today"
_NUMBER_FIELDS: Final = (models.IntegerField, models.FloatField, models.DecimalField)
_DATE_FIELDS: Final = (models.DateField,)  # DateTimeField is a DateField subclass
_MOVE_KEYS: Final = frozenset({"requires", "needs", "stamps", "notify"})
_DELETE_KEYS: Final = frozenset({"when", "blocked_by"})
_BOUND_KEYS: Final = frozenset({"min", "max"})
_UNIQUE_KEYS: Final = frozenset({"fields", "where"})

_UNCHECKED: ContextVar[str | None] = ContextVar("karni_rules_unchecked", default=None)
_CLOCK: ContextVar[dt.datetime | None] = ContextVar("karni_rules_clock", default=None)
_SILENT: ContextVar[str | None] = ContextVar("karni_rules_silent", default=None)
#: An entry of a row filter that is left out (``$me`` with nobody signed in).
_SKIP: Final = object()


# errors -------------------------------------------------------------------------


class RuleViolation(KarniError, ValueError):
    """A write breaks a rule of ``class Karni`` (``E990`` to ``E996``): the API answers 400.

    ``field`` names the field the refusal is about (``None`` for the row).
    """

    def __init__(self, message: str, *, code: str, field: str | None = None) -> None:
        super().__init__(message, code=code)
        self.field = field

    def as_validation_error(self) -> ValidationError:
        """The same refusal as a Django ``ValidationError`` (forms, ``full_clean()``)."""
        error = ValidationError(f"{self.code}: {self.message}", code=self.code)
        if self.field:
            return ValidationError({self.field: [error]})
        return error


class DeleteRefused(KarniConflict):
    """A delete ``Karni.delete`` refuses: children still point at the row, or its state (E995)."""

    code = "E995"


class UniqueConflict(KarniConflict):
    """The database refused a duplicate of a ``Karni.unique`` rule (E991, HTTP 409)."""

    code = "E991"


# declarations ---------------------------------------------------------------------


@dataclass(frozen=True)
class Bound:
    """``bounds``: the lowest and highest value of one field (``None``: no limit)."""

    field: str
    min: Any = None
    max: Any = None


@dataclass(frozen=True)
class Unique:
    """``unique``: fields whose values are unique among the live rows a filter keeps."""

    fields: tuple[str, ...]
    where: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Move:
    """``moves``: what a move of ``field`` into ``to`` (``True`` for a boolean) needs and stamps."""

    key: str
    field: str
    to: Any
    requires: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    stamps: tuple[str, ...] = ()
    #: A path from the row to the user an email about the move goes to (``member``).
    notify: str | None = None


@dataclass(frozen=True)
class DeleteRule:
    """``delete``: the state a deletable row is in, and the related rows that block it."""

    when: Mapping[str, Any] | None = None
    blocked_by: tuple[tuple[str, Mapping[str, Any] | None], ...] = ()


@dataclass(frozen=True)
class Rules:
    """Every rule of one model, parsed and checked (:func:`rules_of`)."""

    bounds: tuple[Bound, ...] = ()
    unique: tuple[Unique, ...] = ()
    targets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    frozen: Mapping[str, Any] = field(default_factory=dict)
    delete: DeleteRule | None = None
    moves: tuple[Move, ...] = ()

    @property
    def active(self) -> bool:
        """Whether a save has anything to check."""
        return bool(self.bounds or self.unique or self.targets or self.frozen or self.moves)

    def tracked(self) -> set[str]:
        """The fields whose stored value decides whether a rule applies to an update."""
        names = {bound.field for bound in self.bounds}
        for unique in self.unique:
            names.update(unique.fields)
            names.update(_first_segments(unique.where or {}))
        for name, spec in self.targets.items():
            names.add(name)
            names.update(_row_refs(spec))
        names.update(self.frozen)
        for move in self.moves:
            names.add(move.field)
            names.update(move.stamps)
        return names


_RULES: dict[type[models.Model], Rules] = {}


def clear_caches() -> None:
    """Forget the parsed rules (tests that change ``class Karni`` at run time)."""
    _RULES.clear()


def rules_of(model: type[models.Model]) -> Rules:
    """``model``'s rules, parsed once (``E998`` when a declaration cannot work)."""
    found = _RULES.get(model)
    if found is None:
        found = _parse(model)
        _RULES[model] = found
    return found


def _bad(model: type[models.Model], option: str, problem: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(f"{model.__name__}.Karni.{option}: {problem}", code="E998")


def _field(model: type[models.Model], option: str, name: Any) -> models.Field[Any, Any]:
    if not isinstance(name, str):
        raise _bad(model, option, f"{name!r} is not a field name.")
    try:
        found = model._meta.get_field(name)
    except FieldDoesNotExist:
        raise _bad(model, option, f"{model.__name__} has no field {name!r}.") from None
    if not getattr(found, "concrete", False):
        raise _bad(model, option, f"{name!r} is not a column of {model.__name__}.")
    return found  # type: ignore[return-value]


def _parse(model: type[models.Model]) -> Rules:
    return Rules(
        bounds=_parse_bounds(model, karni_option(model, "bounds")),
        unique=_parse_unique(model, karni_option(model, "unique")),
        targets=_parse_targets(model, karni_option(model, "targets")),
        frozen=_parse_frozen(model, karni_option(model, "frozen")),
        delete=_parse_delete(model, karni_option(model, "delete")),
        moves=_parse_moves(model, karni_option(model, "moves")),
    )


def _mapping(model: type[models.Model], option: str, value: Any, example: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _bad(model, option, f"must be a dict, e.g. {example}. Got {value!r}.")
    return value


def _parse_bounds(model: type[models.Model], declared: Any) -> tuple[Bound, ...]:
    found: list[Bound] = []
    example = '{"quantity": {"min": 1}}'
    for name, spec in _mapping(model, "bounds", declared, example).items():
        target = _field(model, "bounds", name)
        if not isinstance(target, _NUMBER_FIELDS + _DATE_FIELDS):
            raise _bad(
                model,
                "bounds",
                f"{name!r} is a {type(target).__name__}: bounds apply to numbers, dates and "
                "datetimes.",
            )
        if not isinstance(spec, Mapping) or not spec or set(spec) - _BOUND_KEYS:
            raise _bad(model, "bounds", f"{name!r} takes {{min, max}}, e.g. {example}.")
        for key, value in spec.items():
            _bound_value(model, target, key, value)
        found.append(Bound(name, spec.get("min"), spec.get("max")))
    return tuple(found)


def _bound_value(model: type[models.Model], target: Any, key: str, value: Any) -> None:
    where = f"{target.name}.{key}"
    if value is None:
        return
    if isinstance(target, _DATE_FIELDS):
        if value in (NOW, TODAY):
            return
        try:
            parsed = target.to_python(value)
        except ValidationError:
            parsed = None
        if parsed is None:
            raise _bad(model, "bounds", f"{where} is {value!r}: write $now, $today or a date.")
        return
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise _bad(model, "bounds", f"{where} is {value!r}: write a number.")
    try:
        Decimal(str(value))
    except InvalidOperation:
        raise _bad(model, "bounds", f"{where} is {value!r}: write a number.") from None


def _parse_unique(model: type[models.Model], declared: Any) -> tuple[Unique, ...]:
    if declared is None:
        return ()
    example = '[["slot", "member"], {"fields": ["user"], "where": {"active": True}}]'
    if not isinstance(declared, list | tuple):
        raise _bad(model, "unique", f"must be a list, e.g. {example}. Got {declared!r}.")
    found: list[Unique] = []
    for entry in declared:
        if isinstance(entry, Mapping):
            if set(entry) - _UNIQUE_KEYS or "fields" not in entry:
                raise _bad(model, "unique", f"{entry!r} takes {{fields, where}}.")
            names, where = entry["fields"], entry.get("where")
        else:
            names, where = entry, None
        if isinstance(names, str) or not isinstance(names, list | tuple) or not names:
            raise _bad(model, "unique", f"{entry!r} needs a list of fields, e.g. {example}.")
        for name in names:
            _field(model, "unique", name)
        if where is not None:
            _check_filter(model, "unique", model, where, static=True)
        found.append(Unique(tuple(names), where or None))
    return tuple(found)


def _parse_targets(model: type[models.Model], declared: Any) -> dict[str, Mapping[str, Any]]:
    found: dict[str, Mapping[str, Any]] = {}
    example = '{"listing": {"active": True}}'
    for name, spec in _mapping(model, "targets", declared, example).items():
        relation = _field(model, "targets", name)
        if not (relation.many_to_one or relation.one_to_one):
            raise _bad(model, "targets", f"{name!r} is not a foreign key.")
        target = relation.related_model
        if not isinstance(target, type):
            raise _bad(model, "targets", f"{name!r} points at a model that is not loaded.")
        _check_filter(model, f"targets[{name!r}]", target, spec, row=model)
        found[name] = spec
    return found


def _parse_frozen(model: type[models.Model], declared: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    example = '{"slot": True, "value": {"stage": "won"}}'
    for name, spec in _mapping(model, "frozen", declared, example).items():
        _field(model, "frozen", name)
        if spec is not True:
            _check_filter(model, f"frozen[{name!r}]", model, spec, row=model)
        found[name] = spec
    return found


def _parse_delete(model: type[models.Model], declared: Any) -> DeleteRule | None:
    if declared is None:
        return None
    example = '{"when": {"status": "pending"}, "blocked_by": ["Deal"]}'
    spec = _mapping(model, "delete", declared, example)
    if not spec or set(spec) - _DELETE_KEYS:
        raise _bad(model, "delete", f"takes {{when, blocked_by}}, e.g. {example}.")
    when = spec.get("when")
    if when is not None:
        _check_filter(model, "delete.when", model, when, row=model)
    blocked = spec.get("blocked_by") or ()
    pairs: list[tuple[str, Mapping[str, Any] | None]] = []
    items = blocked.items() if isinstance(blocked, Mapping) else [(ref, None) for ref in blocked]
    if isinstance(blocked, str):
        raise _bad(model, "delete", f"blocked_by is a list of entities, e.g. [{blocked!r}].")
    for ref, condition in items:
        related, _fk = _relation(model, "delete.blocked_by", ref)
        if condition is not None:
            _check_filter(model, f"delete.blocked_by[{ref!r}]", related, condition, row=model)
        pairs.append((str(ref), condition))
    return DeleteRule(when or None, tuple(pairs))


def _state_fields(model: type[models.Model]) -> list[Any]:
    from karni.fields.state import StateField

    return [f for f in model._meta.concrete_fields if isinstance(f, StateField)]


def _move_target(model: type[models.Model], key: str) -> tuple[str, Any]:
    states = _state_fields(model)
    name, colon, state = key.partition(":")
    if colon:
        found = next((f for f in states if f.name == name), None)
        if found is None or state not in found.machine.states:
            raise _bad(model, "moves", f"{key!r} names no state of a StateField {name!r}.")
        return name, state
    owners = [f for f in states if key in f.machine.states]
    flag: Any = None
    try:
        flag = model._meta.get_field(key)
    except FieldDoesNotExist:
        flag = None
    is_flag = isinstance(flag, models.BooleanField)
    if len(owners) + int(is_flag) > 1:
        raise _bad(model, "moves", f"{key!r} is ambiguous: write <field>:{key}.")
    if owners:
        return owners[0].name, key
    if is_flag:
        return key, True
    raise _bad(
        model,
        "moves",
        f"{key!r} is not a state of {model.__name__} or a boolean field of it.",
    )


def _names(model: type[models.Model], option: str, value: Any) -> tuple[str, ...]:
    items = [value] if isinstance(value, str) else list(value or [])
    for item in items:
        if not isinstance(item, str):
            raise _bad(model, option, f"{item!r} is not a name.")
    return tuple(items)


def _parse_moves(model: type[models.Model], declared: Any) -> tuple[Move, ...]:
    found: list[Move] = []
    example = '{"lost": {"requires": ["lost_reason"], "stamps": ["closed_at"]}}'
    for key, spec in _mapping(model, "moves", declared, example).items():
        if not isinstance(spec, Mapping) or not spec or set(spec) - _MOVE_KEYS:
            raise _bad(model, "moves", f"{key!r} takes {{requires, needs, stamps}}: {example}.")
        state_field, to = _move_target(model, str(key))
        requires = _names(model, "moves", spec.get("requires"))
        for name in requires:
            _field(model, f"moves[{key!r}].requires", name)
        stamps = _names(model, "moves", spec.get("stamps"))
        for name in stamps:
            target = _field(model, f"moves[{key!r}].stamps", name)
            if not isinstance(target, _DATE_FIELDS):
                raise _bad(model, "moves", f"stamps {name!r} is not a date or datetime field.")
        needs = _names(model, "moves", spec.get("needs"))
        for ref in needs:
            _relation(model, f"moves[{key!r}].needs", ref)
        notify = spec.get("notify")
        if notify is not None:
            _user_path(model, f"moves[{key!r}].notify", notify)
        found.append(Move(str(key), state_field, to, requires, needs, stamps, notify))
    return tuple(found)


def _user_path(model: type[models.Model], option: str, path: Any) -> None:
    """``E998`` unless ``path`` leads from ``model`` through relations to the user model."""
    from django.contrib.auth import get_user_model

    if not isinstance(path, str) or not path:
        raise _bad(model, option, f"{path!r} is not a path to the user.")
    current: Any = model
    for part in path.split(LOOKUP_SEP):
        try:
            found = current._meta.get_field(part)
        except FieldDoesNotExist:
            raise _bad(model, option, f"{path!r}: {current.__name__} has no {part!r}.") from None
        current = found.related_model
        if not isinstance(current, type):
            raise _bad(model, option, f"{path!r}: {part} is not a relation.")
    if current is not get_user_model():
        raise _bad(model, option, f"{path!r} ends at {current.__name__}, not the user.")


# relation references ------------------------------------------------------------------


def _relation(model: type[models.Model], option: str, ref: Any) -> tuple[type[models.Model], str]:
    """``(related model, its foreign key)`` for ``Deal``, ``Deal.company`` or ``crm.Deal``."""
    if not isinstance(ref, str) or not ref:
        raise _bad(model, option, f"{ref!r} is not an entity name.")
    parts = ref.split(".")
    field_name = parts.pop() if len(parts) > 1 and parts[-1][:1].islower() else None
    if len(parts) == 1:
        app_label, name = model._meta.app_label, parts[0]
    elif len(parts) == 2:
        app_label, name = parts
    else:
        raise _bad(model, option, f"{ref!r} is not Entity, Entity.field or app.Entity.")
    try:
        related = django_apps.get_model(app_label, name)
    except LookupError:
        raise _bad(model, option, f"{ref!r}: no model {app_label}.{name}.") from None
    keys = [
        f.name
        for f in related._meta.concrete_fields
        if (f.many_to_one or f.one_to_one)
        and isinstance(f.related_model, type)
        and issubclass(model, f.related_model)
    ]
    if field_name is not None:
        if field_name not in keys:
            raise _bad(model, option, f"{ref!r}: {name}.{field_name} does not point at it.")
        return related, field_name
    if len(keys) != 1:
        which = "none" if not keys else ", ".join(keys)
        raise _bad(
            model,
            option,
            f"{ref!r}: {name} has {len(keys)} foreign keys to {model.__name__} ({which}). "
            f"Name one: {name}.<field>.",
        )
    return related, keys[0]


def related_rows(instance: models.Model, ref: str, condition: Mapping[str, Any] | None) -> Any:
    """The live rows of the relation reference ``ref`` that point at ``instance``."""
    related, key = _relation(type(instance), "rules", ref)
    rows = related._default_manager.filter(**{key: instance.pk})
    if condition:
        q = filter_q(condition, row=instance)
        if q is not None:
            rows = rows.filter(q)
    return rows


# row filters --------------------------------------------------------------------------


def _first_segments(spec: Mapping[str, Any]) -> set[str]:
    return {str(key).split(LOOKUP_SEP, 1)[0] for key in spec}


def _row_refs(spec: Mapping[str, Any]) -> set[str]:
    """The fields of the written row a filter reads (``$enrolment__course``: ``enrolment``)."""
    found: set[str] = set()
    for value in spec.values():
        inner = value["not"] if isinstance(value, Mapping) and set(value) == {"not"} else value
        if isinstance(inner, str) and inner.startswith("$") and inner not in (ME, NOW, TODAY):
            found.add(inner[1:].split(LOOKUP_SEP, 1)[0])
    return found


def _check_filter(
    model: type[models.Model],
    option: str,
    target: type[models.Model],
    spec: Any,
    *,
    row: type[models.Model] | None = None,
    static: bool = False,
) -> None:
    """Raise ``E998`` for a row filter that cannot be read against ``target``."""
    if not isinstance(spec, Mapping) or not spec:
        raise _bad(
            model,
            option,
            f"{spec!r} is not a row filter: write {{field: value}}, e.g. {{'active': True}}.",
        )
    for key, value in spec.items():
        if not isinstance(key, str) or not key:
            raise _bad(model, option, f"{key!r} is not a field path.")
        parts = key.split(LOOKUP_SEP)
        if len(parts) > 1 and parts[-1] in LOOKUPS:
            parts = parts[:-1]
        current: Any = target
        for part in parts:
            if part == "pk":
                part = current._meta.pk.name
            try:
                found = current._meta.get_field(part)
            except FieldDoesNotExist:
                raise _bad(model, option, f"{key!r}: {current.__name__} has no {part!r}.") from None
            if found.is_relation and isinstance(found.related_model, type):
                current = found.related_model
        inner = value["not"] if isinstance(value, Mapping) and set(value) == {"not"} else value
        if isinstance(inner, Mapping):
            raise _bad(model, option, f"{key!r}: a value is a literal, a $ name or {{not: ...}}.")
        values = inner if isinstance(inner, list | tuple) else [inner]
        for item in values:
            if not (isinstance(item, str) and item.startswith("$")):
                continue
            if static:
                raise _bad(model, option, f"{key!r}: {item} is not a fixed value. Write a literal.")
            if item in (ME, NOW, TODAY):
                continue
            if row is None:
                raise _bad(model, option, f"{key!r}: {item} names no row here.")
            first = item[1:].split(LOOKUP_SEP, 1)[0]
            try:
                row._meta.get_field(first)
            except FieldDoesNotExist:
                raise _bad(model, option, f"{key!r}: {row.__name__} has no {first!r}.") from None


@dataclass(frozen=True)
class _Context:
    user: Any
    now: dt.datetime
    row: models.Model | None


def _now() -> dt.datetime:
    return _CLOCK.get() or timezone.now()


def _context(row: models.Model | None = None) -> _Context:
    from karni.middleware import get_current_user

    return _Context(get_current_user(), _now(), row)


def _walk(row: models.Model | None, path: str) -> Any:
    value: Any = row
    for part in path.split(LOOKUP_SEP):
        if value is None:
            return None
        value = getattr(value, part, None)
    return value


def _resolve(value: Any, ctx: _Context) -> Any:
    if isinstance(value, list | tuple):
        resolved = [_resolve(item, ctx) for item in value]
        return _SKIP if any(item is _SKIP for item in resolved) else resolved
    if not (isinstance(value, str) and value.startswith("$")):
        return value
    if value == ME:
        return ctx.user if ctx.user is not None else _SKIP
    if value == NOW:
        return ctx.now
    if value == TODAY:
        return timezone.localdate(ctx.now)
    return _walk(ctx.row, value[1:])


def filter_q(
    spec: Mapping[str, Any], *, row: models.Model | None = None, ctx: Any = None
) -> Q | None:
    """The ``Q`` of a row filter, its ``$`` values resolved (``None`` when every entry is left out).

    ``row`` is the row being written, for ``$<path>`` values; the signed-in
    user (``$me``) comes from :func:`karni.middleware.get_current_user`.
    """
    context: _Context = ctx if ctx is not None else _context(row)
    q: Q | None = None
    for key, raw in spec.items():
        negate = isinstance(raw, Mapping) and set(raw) == {"not"}
        value = _resolve(raw["not"] if negate else raw, context)
        if value is _SKIP:
            continue
        part = Q(**{key: value})
        part = ~part if negate else part
        q = part if q is None else q & part
    return q


def _show(value: Any) -> str:
    if isinstance(value, Mapping) and set(value) == {"not"}:
        return f"not {_show(value['not'])}"
    if isinstance(value, str):
        return {ME: "you", NOW: "now", TODAY: "today"}.get(value, value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_show(item) for item in value) + "]"
    return str(value)


def describe_filter(spec: Mapping[str, Any]) -> str:
    """A row filter in words: ``active = true, seller__user = not you``."""
    return ", ".join(f"{key} = {_show(value)}" for key, value in spec.items())


def _matches(instance: models.Model, spec: Mapping[str, Any]) -> bool:
    """Whether the unsaved ``instance`` matches a static filter of its own fields (``unique``)."""
    for key, raw in spec.items():
        negate = isinstance(raw, Mapping) and set(raw) == {"not"}
        value = raw["not"] if negate else raw
        parts = key.split(LOOKUP_SEP)
        lookup = parts.pop() if len(parts) > 1 and parts[-1] in LOOKUPS else "exact"
        if len(parts) != 1:
            return True  # a path through a relation: the database decides
        found = instance._meta.get_field(parts[0])
        current = getattr(instance, found.attname)
        holds = _compare(found, current, lookup, value)
        if holds == negate:
            return False
    return True


def _compare(found: Any, current: Any, lookup: str, value: Any) -> bool:
    if lookup == "isnull":
        return (current is None) == bool(value)
    if lookup == "in":
        return _norm(found, current) in [_norm(found, item) for item in value]
    left, right = _norm(found, current), _norm(found, value)
    if lookup == "exact":
        return bool(left == right)
    if left is None or right is None:
        return False
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
    }[lookup]


def _norm(found: Any, value: Any) -> Any:
    if value is None:
        return None
    try:
        return found.to_python(value)
    except (ValidationError, TypeError, ValueError):
        return value


# unique: the partial index, its name and its conflict -------------------------------


class UniqueRule(LiveUniqueConstraint):
    """A ``LiveUniqueConstraint`` made from ``class Karni: unique``.

    It migrates as a ``LiveUniqueConstraint``; Karni checks it before the
    write (``E991``, 400) instead of DRF, and names it when the database
    refuses a duplicate under a race (409).
    """


def unique_constraints(model: type[models.Model]) -> list[UniqueRule]:
    """The constraints ``model``'s ``Karni.unique`` makes (named, conditions built)."""
    found: list[UniqueRule] = []
    for unique in _parse_unique(model, karni_option(model, "unique")):
        columns = [model._meta.get_field(name).column for name in unique.fields]
        condition = None
        if unique.where:
            condition = filter_q(unique.where, ctx=_Context(None, timezone.now(), None))
        found.append(
            UniqueRule(
                fields=list(unique.fields),
                condition=condition,
                name=object_name(model, columns, "live_uniq"),
            )
        )
    return found


def _apply_unique(sender: type[models.Model], **kwargs: Any) -> None:
    """Add ``Karni.unique`` to the model's constraints, so its migration creates the index."""
    from django.db.migrations.state import StateApps

    opts = sender._meta
    if opts.abstract or opts.proxy or sender.__module__ == "__fake__":
        return
    if isinstance(opts.apps, StateApps) or karni_option(sender, "unique") is None:
        return
    try:
        wanted = unique_constraints(sender)
    except KarniImproperlyConfigured:
        return  # karni check reports it (E998); a model must still load
    names = {constraint.name for constraint in opts.constraints}
    added = [constraint for constraint in wanted if constraint.name not in names]
    if added:
        opts.constraints = [*opts.constraints, *added]
        opts.original_attrs["constraints"] = opts.constraints
        opts.__dict__.pop("total_unique_constraints", None)


class_prepared.connect(_apply_unique, dispatch_uid="karni.rules.unique")


def unique_conflict(
    found: Violation,
    model: type[models.Model],
    instance: models.Model | None,
    using: str | None,
) -> KarniError | None:
    """The database refused a duplicate of a :class:`UniqueRule`: ``E991`` (409)."""
    if found.kind != "unique":
        return None
    for constraint in model._meta.constraints:
        if not isinstance(constraint, UniqueRule):
            continue
        columns = [model._meta.get_field(name).column for name in constraint.fields]
        named = same_constraint(constraint.name, found.constraint)
        sqlite = found.constraint is None and all(
            f"{model._meta.db_table}.{column}" in found.message for column in columns
        )
        if named or sqlite:
            return UniqueConflict(
                _unique_message(model, constraint.fields),
                field=constraint.fields[0],
                details={"fields": list(constraint.fields)},
            )
    return None


def _unique_message(model: type[models.Model], names: Any) -> str:
    shown = ", ".join(names)
    return (
        f"A {model._meta.verbose_name} with the same {shown} already exists "
        f"({model.__name__}.Karni.unique)."
    )


# the checks -----------------------------------------------------------------------------


@contextmanager
def unchecked(reason: str) -> Iterator[None]:
    """Skip every rule of this module inside the block (data loading); ``reason`` is required.

    The unique index still refuses a duplicate: it lives in the database.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise KarniValueError(
            "unchecked() needs reason='...': say why the rules of class Karni do not apply "
            "here (e.g. 'import of historical rows').",
            code="E998",
        )
    token = _UNCHECKED.set(reason)
    try:
        yield
    finally:
        _UNCHECKED.reset(token)


@contextmanager
def clock(now: dt.datetime) -> Iterator[None]:
    """Read ``$now`` and ``$today`` as ``now`` inside the block, and stamp with it.

    ``karni seed`` runs at its anchor, so demo data relative to a fixed day
    (``seed(now=...)``) passes the rules the same way on every run.
    """
    token = _CLOCK.set(now)
    try:
        yield
    finally:
        _CLOCK.reset(token)


@contextmanager
def silent(reason: str) -> Iterator[None]:
    """Send no move email inside the block (``karni seed``, data loading); the rules still hold."""
    if not isinstance(reason, str) or not reason.strip():
        raise KarniValueError("silent() needs reason='...'.", code="E998")
    token = _SILENT.set(reason)
    try:
        yield
    finally:
        _SILENT.reset(token)


def _written(instance: models.Model, update_fields: Any) -> set[str]:
    fields = instance._meta.concrete_fields
    if update_fields is None:
        return {f.name for f in fields if f.attname in instance.__dict__}
    names = set(update_fields)
    return {f.name for f in fields if f.name in names or f.attname in names}


def _stored(instance: models.Model, names: set[str]) -> dict[str, Any] | None:
    """What the row held for ``names`` (``None``: the row is not there).

    The values the instance was loaded with (:mod:`karni.guards` remembers
    them), else one query for the ones it was not.
    """
    from karni.guards import MISSING, loaded

    model = type(instance)
    attnames = {name: model._meta.get_field(name).attname for name in names}
    found = {name: loaded(instance, attname) for name, attname in attnames.items()}
    missing = {name: attnames[name] for name, value in found.items() if value is MISSING}
    if not missing:
        return found
    row = (
        model._base_manager.using(instance._state.db or "default")
        .filter(pk=instance.pk)
        .values(*missing.values())
        .first()
    )
    if row is None:
        return None
    return {**found, **{name: row[attname] for name, attname in missing.items()}}


def _skew() -> dt.timedelta:
    return dt.timedelta(seconds=int(getattr(settings, "KARNI_RULES_CLOCK_SKEW", 300)))


def _limit(found: Any, value: Any, ctx: _Context, *, low: bool) -> Any:
    if value is None:
        return None
    if isinstance(found, models.DateTimeField):
        if value == NOW:
            return ctx.now - _skew() if low else ctx.now + _skew()
        if value == TODAY:
            start = timezone.localtime(ctx.now).replace(hour=0, minute=0, second=0, microsecond=0)
            return start if low else start + dt.timedelta(days=1) - dt.timedelta(microseconds=1)
    elif isinstance(found, models.DateField) and value in (NOW, TODAY):
        return timezone.localdate(ctx.now)
    return found.to_python(_exact(value))


def _exact(value: Any) -> Any:
    """A bound as written, a float as its text (money takes no binary float, ``E962``)."""
    return str(value) if isinstance(value, float) else value


def _shown_limit(value: Any) -> str:
    return (
        {NOW: "now", TODAY: "today"}.get(value, str(value))
        if isinstance(value, str)
        else str(value)
    )


#: How far inside a ``$now`` / ``$today`` bound :func:`clamp` puts a generated value.
_MARGIN: Final = dt.timedelta(days=1, minutes=10)


def clamp(model: type[models.Model], name: str, value: Any) -> Any:
    """``value`` moved inside ``name``'s bounds (demo and test data that must pass the rules)."""
    if value is None:
        return value
    found: Any = model._meta.get_field(name)
    ctx = _context()
    for bound in rules_of(model).bounds:
        if bound.field != name:
            continue
        low = _limit(found, bound.min, ctx, low=True)
        high = _limit(found, bound.max, ctx, low=False)
        if bound.min in (NOW, TODAY):  # a day inside, so a later "now" still passes
            low = _limit(found, bound.min, _Context(None, ctx.now + _MARGIN, None), low=True)
        if bound.max in (NOW, TODAY):
            high = _limit(found, bound.max, _Context(None, ctx.now - _MARGIN, None), low=False)
        current = _norm(found, value)
        if low is not None and current < low:
            value = low
        elif high is not None and current > high:
            value = high
    return value


def number_limits(model_field: Any) -> tuple[Any, Any]:
    """The literal ``(min, max)`` of a number field's bounds (``None`` for none): the API schema."""
    model = getattr(model_field, "model", None)
    if not isinstance(model, type) or getattr(getattr(model, "_meta", None), "abstract", True):
        return None, None
    if not isinstance(model_field, _NUMBER_FIELDS):
        return None, None
    try:
        bounds = rules_of(model).bounds
    except KarniImproperlyConfigured:
        return None, None
    for bound in bounds:
        if bound.field == model_field.name:
            low = None if bound.min is None else model_field.to_python(_exact(bound.min))
            high = None if bound.max is None else model_field.to_python(_exact(bound.max))
            return low, high
    return None, None


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def check_write(
    instance: models.Model, update_fields: Any = None, *, stamp: bool = True
) -> set[str]:
    """Check a write of ``instance`` against its rules; returns the stamped fields to save too.

    Raises :class:`RuleViolation` for the first rule it breaks. With
    ``stamp=False`` (``clean()``) nothing is changed on the instance.
    """
    if _UNCHECKED.get() is not None:
        return set()
    model = type(instance)
    rules = rules_of(model)
    if not rules.active:
        return set()
    adding = bool(instance._state.adding) or instance.pk is None
    written = _written(instance, update_fields)
    stored: dict[str, Any] = {}
    if not adding:
        wanted = rules.tracked() & written
        found = _stored(instance, wanted) if wanted else {}
        if found is None:
            adding = True
        else:
            stored = found
    ctx = _context(instance)
    meta = model._meta

    def current(name: str) -> Any:
        return _norm(meta.get_field(name), getattr(instance, meta.get_field(name).attname))

    def changed(name: str) -> bool:
        if name not in written:
            return False
        if adding:
            return True
        return bool(current(name) != _norm(meta.get_field(name), stored.get(name)))

    _check_bounds(instance, rules, ctx, changed, current)
    if not adding:
        _check_frozen(instance, rules, ctx, changed)
    _check_targets(instance, rules, ctx, changed)
    _check_unique(instance, rules, adding, changed)
    return _check_moves(instance, rules, ctx, adding, stored, changed, current, stamp=stamp)


def _check_bounds(instance: Any, rules: Rules, ctx: _Context, changed: Any, current: Any) -> None:
    model = type(instance)
    for bound in rules.bounds:
        if not changed(bound.field):
            continue
        value = current(bound.field)
        if value is None:
            continue
        found = model._meta.get_field(bound.field)
        low = _limit(found, bound.min, ctx, low=True)
        high = _limit(found, bound.max, ctx, low=False)
        if low is not None and value < low:
            raise RuleViolation(
                f"{model.__name__}.{bound.field} is {value}, below its minimum "
                f"{_shown_limit(bound.min)}. Send a value of at least "
                f"{_shown_limit(bound.min)}.",
                code="E990",
                field=bound.field,
            )
        if high is not None and value > high:
            raise RuleViolation(
                f"{model.__name__}.{bound.field} is {value}, above its maximum "
                f"{_shown_limit(bound.max)}. Send a value of at most "
                f"{_shown_limit(bound.max)}.",
                code="E990",
                field=bound.field,
            )


def _check_frozen(instance: Any, rules: Rules, ctx: _Context, changed: Any) -> None:
    model = type(instance)
    for name, condition in rules.frozen.items():
        if not changed(name):
            continue
        if condition is True:
            raise RuleViolation(
                f"{model.__name__}.{name} is set when the row is created and never changes. "
                f"Create a new {model.__name__} instead.",
                code="E994",
                field=name,
            )
        q = filter_q(condition, ctx=ctx)
        if q is None or model._base_manager.filter(pk=instance.pk).filter(q).exists():
            raise RuleViolation(
                f"{model.__name__}.{name} cannot change while {describe_filter(condition)}.",
                code="E994",
                field=name,
            )


def _check_targets(instance: Any, rules: Rules, ctx: _Context, changed: Any) -> None:
    model = type(instance)
    for name, spec in rules.targets.items():
        if not (changed(name) or any(changed(ref) for ref in _row_refs(spec))):
            continue
        relation: Any = model._meta.get_field(name)
        key = getattr(instance, relation.attname)
        if key is None:
            continue
        q = filter_q(spec, ctx=ctx)
        if q is None:
            continue
        target = relation.related_model
        rows = target._default_manager.filter(**{relation.target_field.attname: key})
        if not rows.filter(q).exists():
            raise RuleViolation(
                f"{model.__name__}.{name} must point at a {target.__name__} where "
                f"{describe_filter(spec)}, and {target.__name__} {key} does not.",
                code="E993",
                field=name,
            )


def _check_unique(instance: Any, rules: Rules, adding: bool, changed: Any) -> None:
    model = type(instance)
    for unique in rules.unique:
        watched = (*unique.fields, *_first_segments(unique.where or {}))
        if not adding and not any(changed(name) for name in watched):
            continue
        if unique.where and not _matches(instance, unique.where):
            continue
        values: dict[str, Any] = {}
        for name in unique.fields:
            found = model._meta.get_field(name)
            values[found.attname] = getattr(instance, found.attname)
        if any(value is None for value in values.values()):
            continue  # NULLs never collide in a unique index
        rows = model._default_manager.filter(**values)
        if unique.where:
            q = filter_q(unique.where, ctx=_Context(None, timezone.now(), None))
            rows = rows.filter(q) if q is not None else rows
        if not adding:
            rows = rows.exclude(pk=instance.pk)
        if rows.exists():
            raise RuleViolation(
                _unique_message(model, unique.fields)
                + (f" Rows where {describe_filter(unique.where)} count." if unique.where else ""),
                code="E991",
                field=unique.fields[0],
            )


def _reaches(move: Move, before: Any, after: Any) -> bool:
    if move.to is True:
        return bool(after) and not bool(before)
    return bool(after == move.to and before != after)


def _check_moves(
    instance: Any,
    rules: Rules,
    ctx: _Context,
    adding: bool,
    stored: dict[str, Any],
    changed: Any,
    current: Any,
    *,
    stamp: bool,
) -> set[str]:
    model = type(instance)
    stamped: set[str] = set()
    for move in rules.moves:
        if not changed(move.field):
            continue
        before = None if adding else stored.get(move.field)
        if not _reaches(move, before, current(move.field)):
            continue
        into = "true" if move.to is True else repr(move.to)
        for name in move.requires:
            if _empty(getattr(instance, model._meta.get_field(name).attname)):
                raise RuleViolation(
                    f"{model.__name__}.{move.field} moves to {into} only with {name} set. "
                    f"Send {name} with the move.",
                    code="E996",
                    field=name,
                )
        for ref in move.needs:
            if adding or not related_rows(instance, ref, None).exists():
                raise RuleViolation(
                    f"{model.__name__}.{move.field} moves to {into} only once a {ref} points at "
                    f"it. Add a {ref} first.",
                    code="E996",
                    field=move.field,
                )
        if not stamp:
            continue
        if move.notify is not None and _SILENT.get() is None:
            _on_commit(instance, move)
        for name in move.stamps:
            if not adding and changed(name):
                continue  # the write sets it itself
            if adding and not _empty(getattr(instance, name)):
                continue
            found = model._meta.get_field(name)
            value = (
                ctx.now if isinstance(found, models.DateTimeField) else timezone.localdate(ctx.now)
            )
            setattr(instance, name, value)
            stamped.add(name)
    return stamped


def _on_commit(instance: models.Model, move: Move) -> None:
    """Email the move once the write commits (a rolled-back move sends nothing)."""
    from django.db import transaction

    def send() -> None:
        hook = getattr(instance, "notify_move", None)
        if callable(hook):
            hook(move.key)
        else:
            send_move_email(instance, move.key)

    transaction.on_commit(send, using=instance._state.db or "default")


def send_move_email(instance: models.Model, key: str) -> int:
    """Email the user ``moves[key].notify`` names about the move; returns the messages sent.

    Templates, overridable like any Django template: ``<app>/email/<model>_<key>``
    (``bookings/email/booking_confirmed``) with ``_subject.txt``, ``_body.txt``
    and an optional ``_body.html``, else Karni's ``karni/email/move_*``. The
    context: ``row``, ``key``, ``state``, ``recipient`` and ``frontend``
    (``KARNI_FRONTEND_URL``). Sent through the project's ``EMAIL_BACKEND``
    (the console in development). A user without an email gets nothing.
    The email kind ``<app_label>.<model>_<key>`` switched off in Settings,
    Emails sends nothing (:func:`karni.preferences.email_on`), and the
    project's details give the sender (:func:`karni.preferences.sender`).
    While ``karni.notify`` is installed it is a message kind sent through it
    (:func:`karni.notify.moves.send_move`): an edited text wins, the recipient's
    own switch holds, and it goes to their inbox too (``KARNI_NOTIFY_MOVE_CHANNELS``).
    """
    from django.core.mail import EmailMultiAlternatives
    from django.template import TemplateDoesNotExist
    from django.template.loader import render_to_string, select_template

    from karni import preferences
    from karni.preferences.registry import move_email_name

    move = next(item for item in rules_of(type(instance)).moves if item.key == key)
    if not preferences.email_on(move_email_name(type(instance), key)):
        return 0  # switched off in Settings, Emails
    recipient = _walk(instance, move.notify or "")
    address = getattr(recipient, "email", "") or ""
    if django_apps.is_installed("karni.notify"):
        from karni.notify.moves import send_move

        return send_move(instance, key, recipient)  # the switches, the edits and the inbox
    if not address:
        return 0
    meta = instance._meta
    own = f"{meta.app_label}/email/{meta.model_name}_{key.replace(':', '_')}"
    context = {
        "row": instance,
        "key": key,
        "state": "true" if move.to is True else move.to,
        "recipient": recipient,
        "frontend": str(getattr(settings, "KARNI_FRONTEND_URL", "")).rstrip("/"),
        "model": meta.verbose_name,
    }

    def render(part: str) -> str:
        names = [f"{own}_{part}", f"karni/email/move_{part}"]
        return str(select_template(names).render(context))

    subject = " ".join(render("subject.txt").split())  # one header line
    message = EmailMultiAlternatives(
        subject=subject, body=render("body.txt"), from_email=preferences.sender(), to=[address]
    )
    try:
        html = render_to_string(f"{own}_body.html", context)
    except TemplateDoesNotExist:
        html = None
    if html is not None:
        message.attach_alternative(html, "text/html")
    return int(message.send())


def check_delete(instance: models.Model) -> None:
    """Raise :class:`DeleteRefused` (``E995``) when ``Karni.delete`` keeps ``instance``."""
    if _UNCHECKED.get() is not None or instance.pk is None:
        return
    model = type(instance)
    rule = rules_of(model).delete
    if rule is None:
        return
    name = f"{model.__name__} {instance.pk}"
    if rule.when:
        q = filter_q(rule.when, row=instance)
        if q is not None and not model._base_manager.filter(pk=instance.pk).filter(q).exists():
            raise DeleteRefused(
                f"{name} can be deleted only while {describe_filter(rule.when)}.",
                details={"when": dict(rule.when)},
            )
    for ref, condition in rule.blocked_by:
        count = related_rows(instance, ref, condition).count()
        if count:
            raise DeleteRefused(
                f"{name} has {count} {ref} row(s) pointing at it, so it cannot be deleted. "
                f"Delete or move them first.",
                details={"blocked_by": ref, "count": count},
            )
