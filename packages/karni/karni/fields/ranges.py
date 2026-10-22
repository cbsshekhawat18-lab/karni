"""PostgreSQL range columns: ``DateRangeField`` and ``DateTimeRangeField``.

A booking slot, a stay or a licence period is one value, not two columns
that code must keep in order: ``during = DateTimeRangeField()`` stores
``[2026-10-21 10:00, 2026-10-21 11:00)`` as a native ``tstzrange``. Ranges are
half-open by default (``[)``: the lower bound is included, the upper is not),
so a slot ending at 11:00 and the next one starting at 11:00 *touch* without
overlapping — exactly what back-to-back bookings need, and what
``class Karni: no_overlap`` (:mod:`karni.constraints`) relies on.

These are Django's ``django.contrib.postgres`` range fields with two
additions: a lower bound after the upper one is a validation error (instead
of a ``DataError`` from PostgreSQL), and a stable import path,
``karni.fields``. There is no time-of-day range type in PostgreSQL; a slot is
a ``DateTimeRangeField`` (``tstzrange``), which is what booking needs.

They need PostgreSQL and psycopg: importing them without psycopg raises
``E501`` naming the package to install. SQLite cannot store range values.

Override / escape hatch: use ``django.contrib.postgres.fields`` directly;
``no_overlap`` also accepts a pair of plain fields (``("starts_at",
"ends_at")``), which works on any database.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError

from karni.exceptions import KarniImportError

try:
    from django.contrib.postgres.fields import ranges as _pg
except ImportError as exc:  # psycopg (or psycopg2) is not installed
    raise KarniImportError(
        "karni.fields.DateRangeField / DateTimeRangeField are PostgreSQL range columns and "
        "need psycopg: pip install 'psycopg[binary]' (SQLite cannot store range values, so use "
        "two plain fields, e.g. no_overlap = ('room', ('starts_at', 'ends_at'))).",
        code="E501",
    ) from exc

__all__ = ["DateRangeField", "DateTimeRangeField", "RangeOperators"]

RangeOperators = _pg.RangeOperators


def _ordered(value: Any) -> None:
    """A range whose lower bound is after its upper bound is invalid."""
    lower = getattr(value, "lower", None)
    upper = getattr(value, "upper", None)
    if lower is not None and upper is not None and lower > upper:
        raise ValidationError(
            "The range starts after it ends (%(lower)s > %(upper)s).",
            code="invalid_range",
            params={"lower": lower, "upper": upper},
        )


class DateRangeField(_pg.DateRangeField):  # type: ignore[misc]
    """A ``daterange`` column (PostgreSQL canonicalises it to ``[)``)."""

    default_validators = [_ordered]

    def deconstruct(self) -> Any:
        name, _path, args, kwargs = super().deconstruct()
        return name, "karni.fields.DateRangeField", args, kwargs


class DateTimeRangeField(_pg.DateTimeRangeField):  # type: ignore[misc]
    """A ``tstzrange`` column; a ``(lower, upper)`` tuple is read as ``[)`` (``default_bounds``)."""

    default_validators = [_ordered]

    def deconstruct(self) -> Any:
        name, _path, args, kwargs = super().deconstruct()
        return name, "karni.fields.DateTimeRangeField", args, kwargs
