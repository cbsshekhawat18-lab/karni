"""Bounded numbers whose bounds live in the database: percentages and quantities.

* :class:`PercentField` is a ``DecimalField`` with a CHECK between declared
  bounds, 0 to 100 by default (``PercentField(min_value=-100, max_value=100)``
  for a signed change). ``max_digits`` is derived from the bounds and
  ``decimal_places`` (2 by default) unless given.
* :class:`QuantityField` is a ``PositiveIntegerField``: an integer with
  ``CHECK (col >= 0)`` at the database, for stock, seats, counts and anything
  else that must never go negative, also when two requests race to decrement
  it (the losing UPDATE fails instead of overselling).

Both CHECKs are column constraints that PostgreSQL and SQLite enforce on
every write, ORM or raw SQL. Validators carry the same bounds to forms and
the API.

Override / escape hatch: ``models.DecimalField`` with a
``CheckConstraint`` (percent) and ``models.PositiveIntegerField``
(quantity) are the plain replacements.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core import validators
from django.db import models
from django.db.models import Q

from karni.exceptions import KarniImproperlyConfigured
from karni.fields.base import KarniField

__all__ = ["PercentField", "QuantityField"]


def _decimal(value: Any, what: str) -> Decimal:
    if isinstance(value, float | bool):
        raise KarniImproperlyConfigured(
            f"PercentField({what}={value!r}): give bounds as int or Decimal, not float.",
            code="E963",
        )
    return Decimal(value)


class PercentField(KarniField, models.DecimalField):
    """A percentage with its bounds enforced by a database CHECK (see the module docstring)."""

    plain_django = "models.DecimalField + CheckConstraint"

    def __init__(
        self,
        *args: Any,
        min_value: Any = 0,
        max_value: Any = 100,
        **kwargs: Any,
    ) -> None:
        self.min_value = _decimal(min_value, "min_value")
        self.max_value = _decimal(max_value, "max_value")
        if self.min_value > self.max_value:
            raise KarniImproperlyConfigured(
                f"PercentField(min_value={min_value}, max_value={max_value}): the minimum is "
                "above the maximum.",
                code="E963",
            )
        places = kwargs.setdefault("decimal_places", 2)
        widest = max(abs(self.min_value), abs(self.max_value))
        needed = len(str(int(widest))) + int(places)
        kwargs.setdefault("max_digits", needed)
        if kwargs["max_digits"] < needed:
            raise KarniImproperlyConfigured(
                f"PercentField(max_digits={kwargs['max_digits']}) cannot hold {widest} with "
                f"{places} decimal places. Use max_digits={needed} or leave it out.",
                code="E963",
            )
        super().__init__(*args, **kwargs)
        self.validators.extend(
            [
                validators.MinValueValidator(self.min_value),
                validators.MaxValueValidator(self.max_value),
            ]
        )

    def check_condition(self) -> Any:
        return Q(**{f"{self.name}__gte": self.min_value, f"{self.name}__lte": self.max_value})

    def karni_column(self) -> str:
        return (
            f"PercentField: NUMERIC({self.max_digits},{self.decimal_places}), "
            f"CHECK {self.min_value}..{self.max_value}"
        )

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.min_value != 0:
            kwargs["min_value"] = self.min_value
        if self.max_value != 100:
            kwargs["max_value"] = self.max_value
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        low = max(self.min_value, Decimal(0))
        high = min(self.max_value, Decimal(30)) if self.max_value > low else self.max_value
        high = max(high, low)
        steps = ctx.random.randint(int(low * 4), int(high * 4))
        return (Decimal(steps) / 4).quantize(Decimal(1).scaleb(-self.decimal_places))


class QuantityField(KarniField, models.PositiveIntegerField):
    """A count that can never go negative: ``CHECK (col >= 0)`` in the database."""

    plain_django = "models.PositiveIntegerField"

    def karni_column(self) -> str:
        return "QuantityField: integer, CHECK >= 0"

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        if ctx.unique:
            return ctx.n
        return ctx.random.randint(1, 50)
