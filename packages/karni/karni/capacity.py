"""Consume a limited resource without overselling it: ``reserve()`` and ``release()``.

"N of this exists" — seats in a tier, units in stock, licences in a pool —
is a :class:`~karni.fields.CapacityField` on the resource row, and this is
the one supported way to consume it::

    from django.db import transaction
    from karni.capacity import reserve

    with transaction.atomic():
        reserve(tier, quantity=2)           # or raises CapacityExceeded (E985, HTTP 409)
        Booking.objects.create(tier=tier, quantity=2, ...)

``reserve`` locks the resource row (``SELECT ... FOR UPDATE``), refuses
when fewer than ``quantity`` remain, and decrements in SQL
(``UPDATE ... SET remaining = remaining - 2 WHERE id = ... AND remaining >= 2``).
Two transactions buying the last unit serialise on the row lock: exactly one
wins, the other gets :class:`CapacityExceeded` naming the resource and what
is left. The column's ``CHECK (remaining >= 0)`` refuses an oversell from
any other path, raw SQL included. ``release`` gives units back (a
cancellation), bounded by the field's ``total``.

Both must run inside ``transaction.atomic()`` together with the write that
uses (or frees) the capacity, so the count and the rows that hold it commit
or roll back together; outside a transaction they raise ``E986``.

Overlapping time slots (a room, a guide) are the other limited resource:
``class Karni: no_overlap`` in :mod:`karni.constraints`.

Override / escape hatch: pass ``field=`` when a model has several
CapacityFields; catch :class:`CapacityExceeded` (an ``IntegrityError``) to
offer a waiting list.
"""

from __future__ import annotations

from typing import Any

from django.db import models, router, transaction
from django.db.models import F

from karni.conflicts import KarniConflict, Violation, column_check, same_constraint
from karni.exceptions import KarniValueError
from karni.fields.capacity import CapacityField

__all__ = [
    "CapacityExceeded",
    "capacity_fields",
    "release",
    "reserve",
]


class CapacityExceeded(KarniConflict):
    """Fewer units remain than were asked for (``E985``, HTTP 409).

    ``details``: ``resource`` (model label), ``id``, ``field``, ``remaining``
    and ``requested``.
    """

    code = "E985"


_FIELDS: dict[type[models.Model], tuple[CapacityField, ...]] = {}


def capacity_fields(model: type[models.Model]) -> tuple[CapacityField, ...]:
    """Every :class:`CapacityField` of ``model``."""
    found = _FIELDS.get(model)
    if found is None:
        found = tuple(f for f in model._meta.concrete_fields if isinstance(f, CapacityField))
        _FIELDS[model] = found
    return found


def _field(model: type[models.Model], name: str | None) -> CapacityField:
    fields = capacity_fields(model)
    if name is not None:
        for field in fields:
            if field.name == name:
                return field
    elif len(fields) == 1:
        return fields[0]
    names = ", ".join(field.name for field in fields) or "none"
    if name is None and len(fields) > 1:
        problem = f"{model.__name__} has several CapacityFields ({names}). Pass field='<name>'."
    elif name is None:
        problem = (
            f"{model.__name__} has no CapacityField. Declare one, e.g. remaining = "
            "CapacityField(total='quantity'), and reserve against the row."
        )
    else:
        problem = f"{model.__name__}.{name} is not a CapacityField (its CapacityFields: {names})."
    raise KarniValueError(problem, code="E986")


def _name(resource: models.Model) -> str:
    text = str(resource)
    return f"{type(resource).__name__} {text!r} ({resource.pk})"


def _prepare(
    action: str, resource: models.Model, quantity: Any, field: str | None
) -> tuple[CapacityField, str, Any]:
    if not isinstance(resource, models.Model) or resource.pk is None:
        raise KarniValueError(
            f"{action}() needs a saved model instance that has a CapacityField, got {resource!r}.",
            code="E986",
        )
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise KarniValueError(
            f"{action}({_name(resource)}, quantity={quantity!r}): quantity must be a positive "
            "integer.",
            code="E986",
        )
    found = _field(type(resource), field)
    using = resource._state.db or router.db_for_write(type(resource), instance=resource)
    if not transaction.get_connection(using).in_atomic_block:
        raise KarniValueError(
            f"{action}({_name(resource)}) must run inside transaction.atomic(), together with "
            "the write that uses the capacity, so both commit or roll back as one. Wrap both: "
            f"with transaction.atomic(): {action}(...); <create or update the row>.",
            code="E986",
        )
    return found, using, type(resource)._base_manager.db_manager(using)


def _locked(manager: Any, resource: models.Model, field: CapacityField) -> Any:
    row = (
        manager.select_for_update()
        .filter(pk=resource.pk)
        .values(field.attname, *([field.total_field().attname] if field.total else []))  # type: ignore[union-attr]
        .first()
    )
    if row is None:
        raise KarniValueError(
            f"{_name(resource)} no longer exists, so there is no capacity to use.", code="E986"
        )
    return row


def _store(resource: models.Model, field: CapacityField, value: int) -> None:
    from karni.guards import remember_value

    resource.__dict__[field.attname] = value
    remember_value(resource, field.attname, value)


def reserve(resource: models.Model, quantity: int = 1, *, field: str | None = None) -> int:
    """Take ``quantity`` units of ``resource``'s capacity; return how many remain.

    Raises :class:`CapacityExceeded` (``E985``) when fewer remain, and ``E986``
    when called outside ``transaction.atomic()`` or on a model without a
    CapacityField. ``field`` picks one of several CapacityFields.
    """
    found, using, manager = _prepare("reserve", resource, quantity, field)
    row = _locked(manager, resource, found)
    remaining = row[found.attname]
    if remaining < quantity:
        raise _exceeded(resource, found, remaining, quantity)
    updated = manager.filter(pk=resource.pk, **{f"{found.attname}__gte": quantity}).update(
        **{found.attname: F(found.attname) - quantity}
    )
    if not updated:  # a backend without row locks (SQLite) lost the race
        current = manager.filter(pk=resource.pk).values_list(found.attname, flat=True).first()
        raise _exceeded(resource, found, current or 0, quantity)
    _store(resource, found, remaining - quantity)
    return int(remaining - quantity)


def release(resource: models.Model, quantity: int = 1, *, field: str | None = None) -> int:
    """Give ``quantity`` units of ``resource``'s capacity back; return how many remain.

    With a ``total`` it never goes above it: releasing more than was reserved
    raises ``E986`` (a double release is a bug, not a refund).
    """
    found, using, manager = _prepare("release", resource, quantity, field)
    row = _locked(manager, resource, found)
    remaining = row[found.attname]
    if found.total is not None:
        total = row[found.total_field().attname]  # type: ignore[union-attr]
        if total is not None and remaining + quantity > total:
            raise KarniValueError(
                f"release({_name(resource)}, quantity={quantity}): only {total - remaining} of "
                f"{total} {found.name} are reserved, so {quantity} cannot be released. Release "
                "exactly what was reserved, once (a double release is a bug).",
                code="E986",
            )
    manager.filter(pk=resource.pk).update(**{found.attname: F(found.attname) + quantity})
    _store(resource, found, remaining + quantity)
    return int(remaining + quantity)


def _exceeded(
    resource: models.Model, field: CapacityField, remaining: int, requested: int
) -> CapacityExceeded:
    asked = f"{requested} {'was' if requested == 1 else 'were'} requested"
    if remaining <= 0:
        message = (
            f"{_name(resource)} is sold out ({field.name} = 0), but {asked}. Offer another "
            "resource or a waiting list."
        )
    else:
        message = (
            f"{_name(resource)} has only {remaining} left ({field.name} = {remaining}), "
            f"but {asked}. Ask for at most {remaining}, or offer another resource."
        )
    return CapacityExceeded(
        message,
        field=field.name,
        details={
            "resource": resource._meta.label,
            "id": str(resource.pk),
            "field": field.name,
            "remaining": remaining,
            "requested": requested,
        },
    )


def capacity_conflict(
    found: Violation,
    model: type[models.Model],
    instance: models.Model | None,
    using: str | None,
) -> KarniConflict | None:
    """The CHECK of a CapacityField refused a write: ``E985`` naming the resource and its count."""
    from karni.constraints import capacity_bound

    for field in capacity_fields(model):
        bound = capacity_bound(model, field).name if field.total is not None else None
        over = bound is not None and (
            same_constraint(bound, found.constraint)
            or found.message.split("failed:", 1)[-1].strip() == bound
        )
        if not over and not column_check(found, model, field.column):
            continue
        if over:
            return CapacityExceeded(
                f"{model.__name__}"
                + (f" {instance.pk}" if instance is not None else "")
                + f": the database refused {field.name} above {field.total} (constraint "
                f"{bound}). Give capacity back only with karni.capacity.release(), once per "
                "reservation.",
                field=field.name,
                details={
                    "resource": model._meta.label,
                    "id": str(instance.pk) if instance is not None else None,
                    "field": field.name,
                    "constraint": bound,
                },
            )
        current: dict[str, Any] = {}
        if instance is not None and instance.pk is not None:
            names = [field.attname] + ([field.total_field().attname] if field.total else [])  # type: ignore[union-attr]
            alias = using or instance._state.db or "default"
            current = (
                model._base_manager.using(alias).filter(pk=instance.pk).values(*names).first() or {}
            )
        remaining = current.get(field.attname)
        what = f"{model.__name__} {instance.pk}" if instance is not None else model.__name__
        if field.total is not None and instance is not None:
            total = getattr(instance, field.total_field().attname, None)  # type: ignore[union-attr]
            reserved = None
            if remaining is not None and current.get(field.total_field().attname) is not None:  # type: ignore[union-attr]
                reserved = current[field.total_field().attname] - remaining  # type: ignore[union-attr]
            message = (
                f"{what}: {field.total} cannot become {total}"
                + (f" because {reserved} are already reserved" if reserved is not None else "")
                + f" ({field.name} would drop below zero). Release reservations first, or keep "
                f"{field.total} at least at the reserved amount."
            )
        else:
            message = (
                f"{what}: the database refused a write that would take {field.name} below zero "
                "(its CHECK constraint). Consume capacity only with karni.capacity.reserve()."
            )
        return CapacityExceeded(
            message,
            field=field.total if field.total is not None and instance is not None else field.name,
            details={
                "resource": model._meta.label,
                "id": str(instance.pk) if instance is not None else None,
                "field": field.name,
                "remaining": remaining,
            },
        )
    return None
