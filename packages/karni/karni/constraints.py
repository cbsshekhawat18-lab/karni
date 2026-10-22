"""Non-overlapping time slots, enforced by PostgreSQL: ``class Karni: no_overlap``.

A room, a guide or a vehicle can be booked once per slot. Checking for an
overlap in Python and then inserting is a race two requests win together;
an ``EXCLUDE`` constraint makes the database refuse the second row, even
from a raw SQL ``INSERT``::

    from karni.constraints import NoOverlap
    from karni.fields import DateTimeRangeField, StateField

    class Booking(BaseModel):
        room = models.ForeignKey(Room, on_delete=models.PROTECT)
        during = DateTimeRangeField()
        status = StateField(states=["held", "confirmed", "cancelled"],
                            transitions={"held": ["confirmed", "cancelled"],
                                         "confirmed": ["cancelled"]})

        class Karni:
            no_overlap = NoOverlap("room", "during", ignore={"status": ["cancelled"]})

creates (in the model's migration)::

    ALTER TABLE "rooms_booking" ADD CONSTRAINT "rooms_booking_room_during_no_overlap"
        EXCLUDE USING gist ("room_id" WITH =, "during" WITH &&)
        WHERE ("deleted_at" IS NULL AND NOT ("status" IN ('cancelled')));

* **Resource, then range.** Every field but the last is compared with
  ``=`` (needs the ``btree_gist`` extension, which the constraint creates
  with ``CREATE EXTENSION IF NOT EXISTS btree_gist`` the first time it is
  applied); the last is a range field, or a ``("starts_at", "ends_at")``
  pair compared as ``tstzrange(starts_at, ends_at, '[)')``.
* **Who does not block.** Soft-deleted rows never do (``deleted_at IS
  NULL``, on models that have it); ``ignore={"status": [...]}`` lists the
  states that free the slot; ``condition=Q(...)`` adds anything else.
* **Touching is not overlapping.** Ranges are half-open (``[)``): 10:00–11:00
  and 11:00–12:00 do not conflict. ``bounds="[]"`` makes a pair inclusive.
* **The refusal is named.** Saving a conflicting row raises
  :class:`OverlapConflict` (``E984``, HTTP 409) naming the existing row and
  its range; the admin shows it as a form error before saving.

Shorthand: ``no_overlap = ("room", "during")`` is ``NoOverlap("room",
"during")``; a list declares several. The constraint is also a plain Django
constraint: ``Meta.constraints = [NoOverlap(...)]`` works the same.

On SQLite (and any other backend) there is no ``EXCLUDE``: the constraint
creates nothing and system check ``karni.W980`` says so on every boot.

Override / escape hatch: ``name=`` for the constraint name, ``condition=``
for extra rows to exempt, ``include_deleted=True`` to let soft-deleted rows
block too, or Django's own ``ExclusionConstraint`` in ``Meta.constraints``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from functools import reduce
from operator import and_
from typing import Any

from django.contrib.postgres.constraints import ExclusionConstraint
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import DEFAULT_DB_ALIAS, connections, models
from django.db.models import CheckConstraint, F, Func, Q
from django.db.models.signals import class_prepared

from karni.conflicts import KarniConflict, Violation, same_constraint
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

__all__ = [
    "CapacityBound",
    "NoOverlap",
    "OverlapConflict",
    "RangeOf",
    "capacity_bound",
    "no_overlap_constraints",
]

_PG_NAME_LENGTH = 63
_BOUNDS = ("[)", "(]", "()", "[]")


class OverlapConflict(KarniConflict):
    """The slot is taken: another row overlaps it (``E984``, HTTP 409).

    ``details``: ``constraint``, ``existing`` (its primary key, when known),
    ``range`` and the resource values.
    """

    code = "E984"


def _range_function(field: Any) -> str:
    if isinstance(field, models.DateTimeField):
        return "TSTZRANGE"
    if isinstance(field, models.DateField):
        return "DATERANGE"
    if isinstance(field, models.DecimalField | models.FloatField):
        return "NUMRANGE"
    return "INT8RANGE"


class RangeOf(Func):  # type: ignore[misc]
    """``tstzrange(<start>, <end>, '[)')`` over two plain columns (``daterange`` for dates)."""

    def __init__(self, start: Any, end: Any, bounds: str = "[)") -> None:
        if bounds not in _BOUNDS:
            raise KarniImproperlyConfigured(
                f"RangeOf bounds must be one of {', '.join(_BOUNDS)}, got {bounds!r}.",
                code="E987",
            )
        self.bounds = bounds
        super().__init__(
            F(start) if isinstance(start, str) else start,
            F(end) if isinstance(end, str) else end,
            output_field=models.Field(),
        )

    def as_sql(self, compiler: Any, connection: Any, **extra: Any) -> Any:
        source = self.get_source_expressions()[0]
        function = _range_function(getattr(source, "output_field", None))
        template = f"%(function)s(%(expressions)s, '{self.bounds}')"
        return super().as_sql(compiler, connection, function=function, template=template, **extra)


def _has_field(model: type[models.Model], name: str) -> bool:
    try:
        model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return True


class NoOverlap(ExclusionConstraint):  # type: ignore[misc]
    """``EXCLUDE USING gist (<resource> WITH =, ..., <range> WITH &&) WHERE (<live rows>)``.

    :param fields: the resource fields (compared with ``=``), then the range:
        a range field name or a ``(start, end)`` pair of plain fields.
    :param ignore: ``{field: [values]}`` — rows holding one of these values
        never block (``{"status": ["cancelled", "refunded"]}``).
    :param include_deleted: let soft-deleted rows block too (default: they never do).
    :param bounds: for a ``(start, end)`` pair, which ends are included (``[)``).
    :param condition: an extra ``Q`` every blocking row must also match.
    :param name: the constraint name (default
        ``<app>_<model>_<fields>_no_overlap``).
    """

    def __init__(
        self,
        *fields: Any,
        name: str | None = None,
        ignore: Mapping[str, Iterable[Any]] | None = None,
        include_deleted: bool = False,
        bounds: str = "[)",
        condition: Q | None = None,
        violation_error_code: str | None = None,
        violation_error_message: str | None = None,
    ) -> None:
        if not fields:
            raise KarniImproperlyConfigured(
                "NoOverlap needs the fields: the resource field(s), then the range, e.g. "
                "NoOverlap('room', 'during') or NoOverlap('room', ('starts_at', 'ends_at')).",
                code="E987",
            )
        *resource, span = fields
        if not all(isinstance(item, str) for item in resource):
            raise KarniImproperlyConfigured(
                f"NoOverlap{fields!r}: every field but the last (the range) must be a field name.",
                code="E987",
            )
        if isinstance(span, list | tuple):
            if len(span) != 2 or not all(isinstance(item, str) for item in span):
                raise KarniImproperlyConfigured(
                    f"NoOverlap{fields!r}: a range given as a pair is (start, end) field names, "
                    f"got {span!r}.",
                    code="E987",
                )
            span = (span[0], span[1])
        elif not isinstance(span, str):
            raise KarniImproperlyConfigured(
                f"NoOverlap{fields!r}: the last item is the range: a range field name or a "
                f"(start, end) pair, got {span!r}.",
                code="E987",
            )
        if bounds not in _BOUNDS:
            raise KarniImproperlyConfigured(
                f"NoOverlap bounds must be one of {', '.join(_BOUNDS)}, got {bounds!r}.",
                code="E987",
            )
        if ignore is not None and not isinstance(ignore, Mapping):
            raise KarniImproperlyConfigured(
                f"NoOverlap ignore= must map a field to the values that free the slot, e.g. "
                f"ignore={{'status': ['cancelled']}}, got {ignore!r}.",
                code="E987",
            )
        self.resource: tuple[str, ...] = tuple(resource)
        self.span: str | tuple[str, str] = span
        self.ignore: dict[str, tuple[Any, ...]] = {
            str(key): tuple(getattr(value, "value", value) for value in values)
            for key, values in (ignore or {}).items()
        }
        self.include_deleted = include_deleted
        self.bounds = bounds
        self.extra_condition = condition
        parts = [*self.resource, *([span] if isinstance(span, str) else span)]
        range_expression: Any = (
            span if isinstance(span, str) else RangeOf(span[0], span[1], bounds=bounds)
        )
        super().__init__(
            name=name or "%(app_label)s_%(class)s_" + "_".join(parts) + "_no_overlap",
            expressions=[*((item, "=") for item in self.resource), (range_expression, "&&")],
            violation_error_code=violation_error_code,
            violation_error_message=violation_error_message,
        )

    # -- declaration ---------------------------------------------------------

    @property
    def range_name(self) -> str:
        """The field a conflict is reported on: the range field, or the pair's start."""
        return self.span if isinstance(self.span, str) else self.span[0]

    def deconstruct(self) -> Any:
        _path, _args, kwargs = super(ExclusionConstraint, self).deconstruct()
        kwargs.pop("expressions", None)
        if self.ignore:
            kwargs["ignore"] = {key: list(values) for key, values in self.ignore.items()}
        if self.include_deleted:
            kwargs["include_deleted"] = True
        if self.bounds != "[)":
            kwargs["bounds"] = self.bounds
        if self.extra_condition is not None:
            kwargs["condition"] = self.extra_condition
        return "karni.constraints.NoOverlap", (*self.resource, self.span), kwargs

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NoOverlap):
            return bool(self.deconstruct() == other.deconstruct())
        return False

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"<NoOverlap: {self.resource + (self.span,)!r} name={self.name!r}>"

    def condition_for(self, model: type[models.Model]) -> Q | None:
        """Which rows block: live ones, minus ``ignore``, within ``condition``."""
        parts: list[Q] = []
        if not self.include_deleted and _has_field(model, "deleted_at"):
            parts.append(Q(deleted_at__isnull=True))
        for field, values in self.ignore.items():
            parts.append(~Q(**{f"{field}__in": list(values)}))
        if self.extra_condition is not None:
            parts.append(self.extra_condition)
        return reduce(and_, parts) if parts else None

    # -- DDL: PostgreSQL only ------------------------------------------------

    def _get_condition_sql(self, compiler: Any, schema_editor: Any, query: Any) -> Any:
        condition = self.condition_for(query.model)
        if condition is None:
            return None
        where = query.build_where(condition)
        sql, params = where.as_sql(compiler, schema_editor.connection)
        return sql % tuple(schema_editor.quote_value(p) for p in params)

    def constraint_sql(self, model: Any, schema_editor: Any) -> Any:
        if schema_editor.connection.vendor != "postgresql":
            return None  # no EXCLUDE outside PostgreSQL: karni.W980 warns
        if self.resource:
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        return super().constraint_sql(model, schema_editor)

    def create_sql(self, model: Any, schema_editor: Any) -> Any:
        if schema_editor.connection.vendor != "postgresql":
            return None
        return super().create_sql(model, schema_editor)

    def remove_sql(self, model: Any, schema_editor: Any) -> Any:
        if schema_editor.connection.vendor != "postgresql":
            return None
        return super().remove_sql(model, schema_editor)

    # -- finding the row that is in the way ----------------------------------

    def _values(self, model: type[models.Model], instance: models.Model) -> dict[str, Any] | None:
        names = [*self.resource, *([self.span] if isinstance(self.span, str) else self.span)]
        found: dict[str, Any] = {}
        for name in names:
            value = getattr(instance, model._meta.get_field(name).attname, None)
            if value is None:
                return None
            found[name] = value
        return found

    def blocks(self, model: type[models.Model], instance: models.Model) -> bool:
        """Whether ``instance`` itself is a row that holds its slot."""
        if not self.include_deleted and getattr(instance, "deleted_at", None) is not None:
            return False
        for field, values in self.ignore.items():
            value = getattr(instance, model._meta.get_field(field).attname, None)
            if getattr(value, "value", value) in values:
                return False
        return True

    def conflicting(
        self, model: type[models.Model], instance: models.Model, using: str
    ) -> models.Model | None:
        """The existing row ``instance`` would overlap, or ``None``."""
        values = self._values(model, instance)
        if values is None or not self.blocks(model, instance):
            return None
        queryset = model._base_manager.using(using).filter(
            **{name: values[name] for name in self.resource}
        )
        if isinstance(self.span, str):
            queryset = queryset.filter(**{f"{self.span}__overlap": values[self.span]})
        else:
            start, end = self.span
            lower = "lte" if self.bounds == "[]" else "lt"
            upper = "gte" if self.bounds == "[]" else "gt"
            queryset = queryset.filter(
                **{f"{start}__{lower}": values[end], f"{end}__{upper}": values[start]}
            )
        condition = self.condition_for(model)
        if condition is not None:
            queryset = queryset.filter(condition)
        if instance.pk is not None and not instance._state.adding:
            queryset = queryset.exclude(pk=instance.pk)
        return queryset.order_by().first()

    def describe(self, model: type[models.Model], row: models.Model) -> str:
        """``Booking 7c1e… (room 3, during [10:00, 11:00), status 'confirmed')``."""
        names = [*self.resource, *([self.span] if isinstance(self.span, str) else self.span)]
        parts = [f"{name} {getattr(row, model._meta.get_field(name).attname)}" for name in names]
        for field in self.ignore:
            parts.append(f"{field} {getattr(row, field)!r}")
        return f"{model.__name__} {row.pk} ({', '.join(parts)})"

    def conflict(
        self, model: type[models.Model], instance: models.Model | None, using: str, detail: str = ""
    ) -> OverlapConflict:
        existing = self.conflicting(model, instance, using) if instance is not None else None
        subject = f"{model.__name__} {instance.pk}" if instance is not None else model.__name__
        resource = ", ".join(self.resource) or "the table"
        if existing is not None:
            what = f"it overlaps {self.describe(model, existing)}"
        else:
            what = f"it overlaps an existing row{f' ({detail})' if detail else ''}"
        values = self._values(model, instance) if instance is not None else None
        return OverlapConflict(
            f"{subject} cannot take that slot: {what}, and {model.__name__} allows one live row "
            f"per {resource} at a time (constraint {self.name}). Pick a free slot, or cancel "
            "the existing row first.",
            field=self.range_name,
            details={
                "constraint": self.name,
                "existing": str(existing.pk) if existing is not None else None,
                "values": {key: str(value) for key, value in (values or {}).items()},
            },
        )

    def validate(
        self,
        model: Any,
        instance: Any,
        exclude: Any = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """What ``full_clean()`` (the admin's forms) runs: a form error naming the existing row."""
        if connections[using].vendor != "postgresql":
            return
        names = {*self.resource, *([self.span] if isinstance(self.span, str) else self.span)}
        if exclude and names & set(exclude):
            return
        existing = self.conflicting(model, instance, using)
        if existing is not None:
            raise ValidationError(
                f"E984: This overlaps {self.describe(model, existing)}. Pick a free slot.",
                code=self.violation_error_code or "E984",
            )


def no_overlap_constraints(model: type[models.Model]) -> tuple[NoOverlap, ...]:
    """The :class:`NoOverlap` constraints of ``model`` (declared either way)."""
    return tuple(c for c in model._meta.constraints if isinstance(c, NoOverlap))


def lock_overlap_resources(instance: models.Model, using: str) -> None:
    """Make writes to one resource take turns: a transaction-scoped advisory lock per resource.

    PostgreSQL checks an ``EXCLUDE`` constraint against rows other
    transactions are still writing, so several bookings of one room at once
    can end in a deadlock instead of the overlap error. With this lock the
    second writer waits for the first to commit, then meets its row and gets
    ``E984``. The locks are taken in one order, so they cannot deadlock each
    other, and released when the transaction ends. Other databases have no
    ``EXCLUDE`` and take no lock.
    """
    from django.db import connections

    connection = connections[using]
    model = type(instance)
    constraints = no_overlap_constraints(model)
    if connection.vendor != "postgresql" or not constraints:
        return
    keys: set[int] = set()
    for constraint in constraints:
        if not constraint.blocks(model, instance):
            continue
        values = [
            getattr(instance, model._meta.get_field(name).attname, None)
            for name in constraint.resource
        ]
        if any(value is None for value in values):
            continue
        text = f"{model._meta.db_table}:{constraint.name}:{values!r}"
        digest = hashlib.blake2b(text.encode(), digest_size=8).digest()
        keys.add(int.from_bytes(digest, "big", signed=True))
    with connection.cursor() as cursor:
        for key in sorted(keys):
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def overlap_conflict(
    found: Violation,
    model: type[models.Model],
    instance: models.Model | None,
    using: str | None,
) -> KarniConflict | None:
    """An ``EXCLUDE`` violation of one of ``model``'s NoOverlap constraints: ``E984``."""
    for constraint in no_overlap_constraints(model):
        if same_constraint(constraint.name, found.constraint):
            detail = (
                found.message.split("DETAIL:", 1)[-1].strip() if "DETAIL:" in found.message else ""
            )
            alias = using or (instance._state.db if instance is not None else None) or "default"
            return constraint.conflict(model, instance, alias, detail)
    return None


# class Karni: no_overlap = ...


def _short(name: str) -> str:
    if len(name) <= _PG_NAME_LENGTH:
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"{name[: _PG_NAME_LENGTH - 9]}_{digest}"


def _declared(model: type[models.Model], declared: Any) -> list[NoOverlap]:
    """``Karni.no_overlap``: a NoOverlap, a field tuple, or a list of either."""
    items = declared if isinstance(declared, list) else [declared]
    found: list[NoOverlap] = []
    for item in items:
        if isinstance(item, NoOverlap):
            constraint = item.clone()
        elif isinstance(item, tuple):
            constraint = NoOverlap(*item)
        else:
            raise KarniImproperlyConfigured(
                f"{model.__name__}.Karni.no_overlap must be NoOverlap(...), a tuple of field "
                f"names ending with the range (('room', 'during')), or a list of them. Got "
                f"{item!r}.",
                code="E987",
            )
        constraint.name = _short(
            constraint.name
            % {"app_label": model._meta.app_label.lower(), "class": model.__name__.lower()}
        )
        found.append(constraint)
    return found


class CapacityBound(CheckConstraint):  # type: ignore[misc]
    """``CHECK ("<counter>" <= "<total>")`` for a ``CapacityField(total=...)``.

    Added to the model's constraints automatically (so its migration creates
    it). Not checked by ``full_clean()``: a save shifts the counter in SQL
    when the total changes, so the in-memory values would mislead; the
    database checks the row it actually writes.
    """

    def validate(self, *args: Any, **kwargs: Any) -> None:
        return None


def capacity_bound(model: type[models.Model], field: Any) -> CapacityBound:
    """The upper-bound constraint of ``model``'s CapacityField ``field``."""
    return CapacityBound(
        condition=Q(**{f"{field.name}__lte": F(field.total)}),
        name=_short(f"{model._meta.db_table}_{field.name}_lte_{field.total}"),
    )


def _apply_karni_constraints(sender: type[models.Model], **kwargs: Any) -> None:
    """Add ``Karni.no_overlap`` and capacity bounds to the model's constraints (for migrations)."""
    from karni.fields.capacity import CapacityField

    opts = sender._meta
    if opts.abstract or opts.proxy or sender.__module__ == "__fake__":
        return  # a migration's historical model carries the constraints its state has
    declared = karni_option(sender, "no_overlap")
    wanted: list[Any] = _declared(sender, declared) if declared else []
    for field in opts.local_concrete_fields:
        if isinstance(field, CapacityField) and field.total is not None:
            wanted.append(capacity_bound(sender, field))
    if not wanted:
        return
    constraints = list(opts.constraints)
    names = {constraint.name for constraint in constraints}
    for constraint in wanted:
        if constraint.name not in names:
            constraints.append(constraint)
            names.add(constraint.name)
    opts.constraints = constraints
    opts.original_attrs["constraints"] = constraints


class_prepared.connect(_apply_karni_constraints, dispatch_uid="karni.constraints.apply")
