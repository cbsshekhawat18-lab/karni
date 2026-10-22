"""Country and currency codes the database itself constrains to ISO lists.

``CountryField`` stores an ISO 3166-1 alpha-2 code (``"DE"``) and
``CurrencyField`` an ISO 4217 code (``"EUR"``). Both are ``CharField``s with
the ISO list as ``choices`` (forms, the admin and the OpenAPI enum get it)
**and** a database ``CHECK (col IN (...))``, so free text cannot get in
through raw SQL, a bulk update or another service writing the table. The
lists ship with Karni (:mod:`karni.fields.iso_data`); no network, no
dependency.

``codes=[...]`` narrows a field to a subset (the countries you ship to),
``extra_codes=[...]`` widens it (``"XK"``, the user-assigned code commonly
used for Kosovo). The CHECK is a named constraint listing the codes, so when
a Karni release updates a list, ``makemigrations`` replaces it
(``RemoveConstraint`` + ``AddConstraint``); the field records the list's
``iso_revision`` so its ``choices`` stay those of the migration that built it.

Override / escape hatch: ``models.CharField(max_length=2, choices=...)``
is the plain replacement (no database CHECK).
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from typing import Any

from django.db import models
from django.db.models import Q

from karni.exceptions import KarniImproperlyConfigured
from karni.fields import iso_data
from karni.fields.base import KarniField

__all__ = [
    "CountryField",
    "CurrencyField",
    "country_codes",
    "currency_codes",
    "minor_units",
]


@cache
def country_codes(revision: str = iso_data.COUNTRY_REVISION) -> frozenset[str]:
    """Every ISO 3166-1 alpha-2 code in ``revision`` (the current one by default)."""
    return frozenset(code for code, _ in iso_data.COUNTRIES[revision])


@cache
def currency_codes(revision: str = iso_data.CURRENCY_REVISION) -> frozenset[str]:
    """Every ISO 4217 code in ``revision`` (the current one by default)."""
    return frozenset(code for code, _ in iso_data.CURRENCIES[revision])


def minor_units(code: str) -> int | None:
    """Decimal places ISO 4217 gives ``code`` (2 unless listed otherwise; ``None``: n/a)."""
    return iso_data.MINOR_UNITS.get(code.upper(), 2)


class _CodeField(KarniField, models.CharField):
    """A code from a shipped ISO list, with ``choices`` and a database CHECK."""

    length: int = 2
    standard: str = ""
    lists: dict[str, tuple[tuple[str, str], ...]] = {}
    current: str = ""

    def __init__(
        self,
        *args: Any,
        codes: Iterable[str] | None = None,
        extra_codes: Iterable[str] = (),
        iso_revision: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._pop_unique(kwargs)
        revision = iso_revision or self.current
        if revision not in self.lists:
            raise KarniImproperlyConfigured(
                f"{type(self).__name__}(iso_revision={revision!r}): Karni ships revisions "
                f"{', '.join(sorted(self.lists))}. Upgrade karni (a newer migration may need "
                "a newer list), or remove the argument.",
                code="E963",
            )
        self.iso_revision = revision
        known = dict(self.lists[revision])
        self.codes = None if codes is None else tuple(code.upper() for code in codes)
        self.extra_codes = tuple(code.upper() for code in extra_codes)
        unknown = sorted(set(self.codes or ()) - set(known))
        if unknown:
            raise KarniImproperlyConfigured(
                f"{type(self).__name__}(codes=...) lists {', '.join(unknown)}, which "
                f"{self.standard} does not assign. Put non-standard codes in extra_codes=[...].",
                code="E963",
            )
        bad = [code for code in self.extra_codes if len(code) != self.length or not code.isalpha()]
        if bad:
            raise KarniImproperlyConfigured(
                f"{type(self).__name__}(extra_codes=...) has {', '.join(bad)}: each must be "
                f"{self.length} letters.",
                code="E963",
            )
        allowed = [code for code, _ in self.lists[revision] if code in (self.codes or known)]
        choices = [(code, known[code]) for code in allowed]
        choices += [(code, code) for code in self.extra_codes if code not in known]
        kwargs.setdefault("max_length", self.length)
        self._listed_choices = "choices" not in kwargs
        kwargs.setdefault("choices", choices)
        super().__init__(*args, **kwargs)

    @property
    def allowed_codes(self) -> tuple[str, ...]:
        """The codes the CHECK admits, in list order."""
        return tuple(str(code) for code, _ in self.flatchoices)

    def to_python(self, value: Any) -> Any:
        value = super().to_python(value)
        return value.strip().upper() if isinstance(value, str) else value

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return value.strip().upper() if isinstance(value, str) else value

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        value = super().pre_save(model_instance, add)
        if isinstance(value, str):
            value = value.strip().upper()
            setattr(model_instance, self.attname, value)
        return value

    def check_condition(self) -> Any:
        condition = Q(**{f"{self.name}__in": list(self.allowed_codes)})
        return condition | Q(**{self.name: ""}) if self.blank and not self.null else condition

    def karni_column(self) -> str:
        scope = "subset" if self.codes is not None else "every code"
        return (
            f"{type(self).__name__}: char({self.max_length}), CHECK {self.standard} "
            f"({scope}, revision {self.iso_revision}, {len(self.allowed_codes)} codes)"
        )

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        self._unique_deconstruct(kwargs)
        if self._listed_choices:
            kwargs.pop("choices", None)  # rebuilt from the list and the arguments below
        if kwargs.get("max_length") == self.length:
            kwargs.pop("max_length")
        kwargs["iso_revision"] = self.iso_revision
        if self.codes is not None:
            kwargs["codes"] = list(self.codes)
        if self.extra_codes:
            kwargs["extra_codes"] = list(self.extra_codes)
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        return ctx.random.choice(self.allowed_codes)


class CountryField(_CodeField):
    """An ISO 3166-1 alpha-2 country code, checked by the database."""

    length = 2
    standard = "ISO 3166-1 alpha-2"
    lists = iso_data.COUNTRIES
    current = iso_data.COUNTRY_REVISION
    plain_django = "models.CharField(max_length=2, choices=...)"


class CurrencyField(_CodeField):
    """An ISO 4217 currency code, checked by the database."""

    length = 3
    standard = "ISO 4217"
    lists = iso_data.CURRENCIES
    current = iso_data.CURRENCY_REVISION
    plain_django = "models.CharField(max_length=3, choices=...)"
