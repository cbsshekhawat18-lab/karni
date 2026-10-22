"""Typed model fields: declare intent, get the correct column, index and constraint.

An agent writing a model reaches for ``FloatField`` for money, a free-text
``CharField`` for a country and a case-sensitive unique email. None of that
fails a test; all of it fails in production. Each field here is the plain
Django field plus what the database must guarantee, enforced by the database
(so raw SQL, bulk updates and other services cannot get around it)::

    from karni.fields import CountryField, MoneyField, QuantityField, SlugField

    class Product(BaseModel):
        name = models.CharField(max_length=200)
        slug = SlugField(populate_from="name")         # unique among live rows
        price = MoneyField(currency="EUR", min_value=0)  # NUMERIC(19,4), no floats
        stock = QuantityField(default=0)                # CHECK (stock >= 0)
        made_in = CountryField()                        # CHECK (made_in IN ISO 3166)

=====================  ============================================  ==============
Field                  Column, constraint, index                     Backends
=====================  ============================================  ==============
``MoneyField``         NUMERIC(19,4), currency declared, no floats   exact on PG
``PercentField``       NUMERIC, CHECK between bounds (0..100)        all
``QuantityField``      integer, CHECK >= 0                           all
``EmailField``         unique on LOWER(email), domain lower-cased    all
``SlugField``          unique (live rows), generated from a field    all
``PhoneField``         E.164, CHECK format                           PG, SQLite
``CountryField``       char(2), CHECK IN ISO 3166-1 alpha-2          all
``CurrencyField``      char(3), CHECK IN ISO 4217                    all
``JSONField``          jsonb; GIN when ``queried=True``              GIN on PG
``SearchField``        generated tsvector + GIN                      PG (degrades)
``ArrayField``         array + GIN                                   PG only
``StateField``         declared states, CHECK IN, legal moves only   all
``CapacityField``      remaining count, CHECK >= 0, reserve()        all
``DateRangeField``     daterange; ``DateTimeRangeField`` tstzrange   PG only
=====================  ============================================  ==============

``LiveUniqueConstraint`` declares uniqueness over live rows of a
soft-deletable model; ``GinIndex``/``GistIndex``/``BrinIndex`` are
PostgreSQL indexes that are a no-op elsewhere; ``CreateExtension`` creates a
PostgreSQL extension from a migration. ``karni schema`` lists what each
declaration created and why; ``docs/fields.md`` has the full reference.

Lifecycle and limited resources (``docs/lifecycle-and-capacity.md``):
``StateField`` moves only along declared transitions, by a conditional
update (:mod:`karni.fields.state`); ``CapacityField`` is consumed with
:func:`karni.capacity.reserve` (:mod:`karni.fields.capacity`); the range
fields back ``class Karni: no_overlap`` (:mod:`karni.fields.ranges`).

Override / escape hatch: every field accepts its Django base field's
arguments and can be replaced by that plain field (``plain_django`` names
it).
"""

from __future__ import annotations

from typing import Any

from karni.fields.base import (
    KarniField,
    SchemaNote,
    contribute_constraint,
    contribute_index,
    is_soft_deletable,
    is_unique,
    schema_notes,
)
from karni.fields.capacity import CapacityField
from karni.fields.constraints import LiveUniqueConstraint
from karni.fields.extensions import CreateExtension, ensure_extension
from karni.fields.indexes import BrinIndex, GinIndex, GistIndex
from karni.fields.iso import CountryField, CurrencyField, country_codes, currency_codes
from karni.fields.money import MoneyField, allocate, quantize, split
from karni.fields.numbers import PercentField, QuantityField
from karni.fields.search import SearchField
from karni.fields.state import StateField
from karni.fields.structured import JSONField
from karni.fields.text import E164Format, EmailField, PhoneField, SlugField, normalize_phone

# ArrayField and the range fields are lazy re-exports (module __getattr__
# below): they need a PostgreSQL driver, and karni.fields must import without one.
__all__ = [  # noqa: F822
    "ArrayField",
    "BrinIndex",
    "CapacityField",
    "CountryField",
    "CreateExtension",
    "CurrencyField",
    "DateRangeField",
    "DateTimeRangeField",
    "E164Format",
    "EmailField",
    "GinIndex",
    "GistIndex",
    "JSONField",
    "KarniField",
    "LiveUniqueConstraint",
    "MoneyField",
    "PercentField",
    "PhoneField",
    "QuantityField",
    "SchemaNote",
    "SearchField",
    "SlugField",
    "StateField",
    "allocate",
    "contribute_constraint",
    "contribute_index",
    "country_codes",
    "currency_codes",
    "ensure_extension",
    "is_soft_deletable",
    "is_unique",
    "normalize_phone",
    "quantize",
    "schema_notes",
    "split",
]

#: The range fields: karni.fields.ranges raises E501 itself without psycopg.
_RANGES = frozenset({"DateRangeField", "DateTimeRangeField"})


def __getattr__(name: str) -> Any:
    """Import the PostgreSQL-only fields on first use (they need psycopg)."""
    if name in _RANGES:
        from karni.fields import ranges

        return getattr(ranges, name)
    if name == "ArrayField":
        try:
            from karni.fields.arrays import ArrayField
        except ImportError as exc:
            from karni.exceptions import KarniImportError

            raise KarniImportError(
                "karni.fields.ArrayField needs a PostgreSQL driver (arrays exist only on "
                "PostgreSQL): pip install 'psycopg[binary]'. For a portable list use "
                "karni.fields.JSONField.",
                code="E501",
            ) from exc
        return ArrayField
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
