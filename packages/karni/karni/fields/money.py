"""Money: ``NUMERIC(19,4)`` with a declared currency, Decimal arithmetic only.

``MoneyField`` is a ``DecimalField`` (19 digits, 4 decimal places: amounts up
to 999,999,999,999,999.9999 with room for sub-cent prices and exchange
results) that

* declares its currency: ``MoneyField(currency="EUR")`` for one fixed ISO
  4217 currency, or ``MoneyField(currency_field="currency")`` naming a
  :class:`~karni.fields.CurrencyField` on the same model for per-row
  currencies. One of the two is required (``karni.E961``);
* refuses floats: assigning ``9.99`` (a binary float) to the attribute, or
  using one in a lookup, raises ``karni.E962``. Ints and ``Decimal`` are
  exact and accepted; strings are parsed by Django as usual;
* rounds with a declared rule: values are quantized to ``decimal_places`` with
  ``rounding`` (``ROUND_HALF_EVEN``, banker's rounding, by default) before
  they reach the database, so the stored value never depends on the
  database's own rounding;
* optionally bounds itself: ``min_value``/``max_value`` become validators and
  a database CHECK (``MoneyField(currency="EUR", min_value=0)``).

:func:`quantize`, :func:`allocate` and :func:`split` do the arithmetic money
needs without ever losing a cent: an allocation always sums to the total.

PostgreSQL stores ``NUMERIC`` exactly. SQLite has no exact decimal storage:
it keeps ``NUMERIC`` as a binary float, exact to 15 significant digits, and
its ``SUM()`` is floating point (``karni.W964`` says so).

Override / escape hatch: ``models.DecimalField(max_digits=19,
decimal_places=4)`` is the plain replacement; every DecimalField argument
works here too.
"""

from __future__ import annotations

import decimal
from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any

from django.core import validators
from django.db import models
from django.db.models import Q
from django.db.models.query_utils import DeferredAttribute

from karni.exceptions import KarniImproperlyConfigured, KarniTypeError
from karni.fields.base import KarniField

__all__ = ["ROUNDING_MODES", "MoneyField", "allocate", "quantize", "split"]

#: The rounding rules ``MoneyField(rounding=...)`` accepts (the ``decimal`` module's).
ROUNDING_MODES = frozenset(
    {
        decimal.ROUND_HALF_EVEN,
        decimal.ROUND_HALF_UP,
        decimal.ROUND_HALF_DOWN,
        decimal.ROUND_UP,
        decimal.ROUND_DOWN,
        decimal.ROUND_CEILING,
        decimal.ROUND_FLOOR,
        decimal.ROUND_05UP,
    }
)


def _exact(value: Any, what: str) -> Decimal:
    """``value`` as an exact Decimal; a float (or bool) raises ``karni.E962``."""
    if isinstance(value, bool) or isinstance(value, float):
        raise KarniTypeError(
            f"{what} got {value!r} ({type(value).__name__}): money is never a binary float, "
            "which cannot represent most cent values exactly. Pass a Decimal "
            f"(Decimal({str(value)!r})), an int, or a string.",
            code="E962",
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        try:
            return Decimal(value)
        except decimal.InvalidOperation as exc:
            raise KarniTypeError(
                f"{what} got {value!r}, which is not a number.", code="E962"
            ) from exc
    raise KarniTypeError(
        f"{what} got {value!r} ({type(value).__name__}); pass a Decimal, an int or a string.",
        code="E962",
    )


def quantize(value: Any, places: int = 2, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    """``value`` rounded to ``places`` decimals with ``rounding`` (exact; floats refused)."""
    return _exact(value, "quantize()").quantize(Decimal(1).scaleb(-places), rounding=rounding)


def allocate(total: Any, ratios: Sequence[Any], places: int = 2) -> list[Decimal]:
    """Split ``total`` by ``ratios`` into amounts of ``places`` decimals that sum to it exactly.

    Largest-remainder method: every share is rounded down, then the units
    left over go one each to the shares with the largest remainders (the
    earliest share wins a tie). ``allocate(Decimal("100"), [1, 1, 1])`` is
    ``[33.34, 33.33, 33.33]``. A negative total allocates its magnitude and
    negates every share.
    """
    amount = quantize(total, places, ROUND_HALF_EVEN)
    weights = [_exact(ratio, "allocate() ratio") for ratio in ratios]
    if not weights or any(weight < 0 for weight in weights) or sum(weights) == 0:
        raise KarniTypeError(
            f"allocate() needs non-negative ratios with a positive sum, got {list(ratios)!r}.",
            code="E962",
        )
    sign = -1 if amount < 0 else 1
    unit = Decimal(1).scaleb(-places)
    units = int((abs(amount) / unit).to_integral_value())
    whole = sum(weights)
    exact_shares = [Decimal(units) * weight / whole for weight in weights]
    floors = [int(share.to_integral_value(rounding=ROUND_DOWN)) for share in exact_shares]
    left = units - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(exact_shares[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += 1
    return [(Decimal(count) * unit * sign).quantize(unit) for count in floors]


def split(total: Any, parts: int, places: int = 2) -> list[Decimal]:
    """``total`` split into ``parts`` near-equal amounts that sum to it exactly."""
    if parts < 1:
        raise KarniTypeError(f"split() needs at least one part, got {parts}.", code="E962")
    return allocate(total, [1] * parts, places)


class _MoneyAttribute(DeferredAttribute):
    """The model attribute: refuses floats on assignment, makes ints exact."""

    def __set__(self, instance: Any, value: Any) -> None:
        field: Any = self.field
        if value is not None and not isinstance(value, str) and not hasattr(value, "as_sql"):
            value = _exact(value, f"{type(instance).__name__}.{field.name}")
        instance.__dict__[field.attname] = value


class MoneyField(KarniField, models.DecimalField):
    """An amount of money (see the module docstring)."""

    descriptor_class = _MoneyAttribute
    plain_django = "models.DecimalField(max_digits=19, decimal_places=4)"

    def __init__(
        self,
        *args: Any,
        currency: str | None = None,
        currency_field: str | None = None,
        rounding: str = ROUND_HALF_EVEN,
        min_value: Any = None,
        max_value: Any = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("max_digits", 19)
        kwargs.setdefault("decimal_places", 4)
        if (currency is None) == (currency_field is None):
            raise KarniImproperlyConfigured(
                "MoneyField needs exactly one currency declaration: "
                'MoneyField(currency="EUR") for one fixed ISO 4217 currency, or '
                'MoneyField(currency_field="currency") naming a CurrencyField on the same '
                "model for a currency per row"
                + (" (it got both)." if currency is not None else "."),
                code="E961",
            )
        if currency is not None:
            from karni.fields.iso import currency_codes

            code = str(currency).upper()
            if code not in currency_codes():
                raise KarniImproperlyConfigured(
                    f"MoneyField(currency={currency!r}): not an ISO 4217 currency code. Use "
                    'the three-letter code, e.g. "EUR", "USD", "INR".',
                    code="E961",
                )
            currency = code
        if rounding not in ROUNDING_MODES:
            raise KarniImproperlyConfigured(
                f"MoneyField(rounding={rounding!r}): use one of the decimal module's modes, "
                "e.g. decimal.ROUND_HALF_EVEN (the default) or decimal.ROUND_HALF_UP.",
                code="E963",
            )
        self.currency = currency
        self.currency_field = currency_field
        self.rounding = rounding
        self.min_value = None if min_value is None else _exact(min_value, "min_value")
        self.max_value = None if max_value is None else _exact(max_value, "max_value")
        super().__init__(*args, **kwargs)
        if self.min_value is not None:
            self.validators.append(validators.MinValueValidator(self.min_value))
        if self.max_value is not None:
            self.validators.append(validators.MaxValueValidator(self.max_value))

    # -- values ------------------------------------------------------------

    def quantize_value(self, value: Any) -> Any:
        """``value`` rounded to the field's places with its declared rule."""
        if value is None or hasattr(value, "as_sql"):
            return value
        where = f"{self.model.__name__}.{self.name}" if hasattr(self, "model") else self.name
        exact = _exact(value, where)
        return exact.quantize(Decimal(1).scaleb(-self.decimal_places), rounding=self.rounding)

    def to_python(self, value: Any) -> Any:
        if isinstance(value, float):
            _exact(value, self.name)
        return super().to_python(value)

    def get_prep_value(self, value: Any) -> Any:
        if isinstance(value, float | bool):
            _exact(value, f"A lookup on {self.name}")
        return self.quantize_value(super().get_prep_value(value))

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        value = super().pre_save(model_instance, add)
        if value is None or isinstance(value, str) or hasattr(value, "as_sql"):
            return value
        rounded = self.quantize_value(value)
        setattr(model_instance, self.attname, rounded)
        return rounded

    def currency_for(self, instance: Any) -> str:
        """The ISO 4217 code ``instance``'s amount is in."""
        if self.currency is not None:
            return self.currency
        value: Any = instance
        for part in str(self.currency_field).split("__"):
            value = getattr(value, part, None)
        return str(value) if value is not None else ""

    # -- database ------------------------------------------------------------

    def check_condition(self) -> Any:
        condition = Q()
        if self.min_value is not None:
            condition &= Q(**{f"{self.name}__gte": self.min_value})
        if self.max_value is not None:
            condition &= Q(**{f"{self.name}__lte": self.max_value})
        return condition or None

    def karni_column(self) -> str:
        currency = (
            f'currency="{self.currency}"'
            if self.currency
            else f'currency_field="{self.currency_field}"'
        )
        bounds = _bounds_text(self.min_value, self.max_value)
        return (
            f"MoneyField({currency}): NUMERIC({self.max_digits},{self.decimal_places}), "
            f"Decimal only, rounded {self.rounding}{bounds}"
        )

    def postgres_only_text(self) -> str:
        return (
            "exact NUMERIC storage: SQLite keeps it as a binary float (exact to 15 significant "
            "digits) and SUM() is floating point"
        )

    def backend_problem(self, connection: Any) -> tuple[str, str] | None:
        if connection.vendor == "sqlite":
            return "warning", self.postgres_only_text()
        return None

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.currency is not None:
            kwargs["currency"] = self.currency
        else:
            kwargs["currency_field"] = self.currency_field
        if self.rounding != ROUND_HALF_EVEN:
            kwargs["rounding"] = self.rounding
        if self.min_value is not None:
            kwargs["min_value"] = self.min_value
        if self.max_value is not None:
            kwargs["max_value"] = self.max_value
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        low = self.min_value if self.min_value is not None else Decimal(5)
        high = self.max_value if self.max_value is not None else low + 495
        cents = ctx.random.randint(int(low * 100), int(high * 100))
        return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def _bounds_text(low: Any, high: Any) -> str:
    if low is None and high is None:
        return ""
    if high is None:
        return f", CHECK >= {low}"
    if low is None:
        return f", CHECK <= {high}"
    return f", CHECK {low}..{high}"
