"""Experimental. Grouped counts and sums a resource declares, under the list's filters and access.

A model declares what may be aggregated, next to its other Karni options::

    from karni.aggregation import TextNumber


    class Product(BaseModel):
        category = models.ForeignKey(Category, on_delete=models.PROTECT)
        region = models.CharField(max_length=20, choices=REGIONS)
        launched_on = models.DateField()
        price = MoneyField(currency="EUR")
        revenue_text = models.CharField(max_length=40, blank=True)  # "$1.2B", "450K"

        class Karni:
            aggregate = {
                "group_by": ["category", "category__parent", "region", "launched_on"],
                "values": ["price", "revenue"],
                "metrics": ["count", "sum", "avg"],  # default: every metric
                "expressions": {"revenue": TextNumber("revenue_text")},
            }

and its viewset answers ``GET /products/aggregate/?group_by=region&metric=sum&value=price``
(:meth:`karni.api.viewsets.BaseViewSet.aggregate`). Nothing is aggregatable
unless it is declared: a field, a relation path or an expression the
declaration does not list is refused with 400 and a code.

``group_by`` takes a field, a relation path (``category__parent``) or an
expression name, and a date or datetime field takes a bucket after a colon
(``launched_on:year``, ``:quarter``, ``:month``). A declared ``launched_on``
allows every bucket, a declared ``launched_on:year`` only that one.
``values`` are the fields, paths or expressions a metric other than a plain
count reads. ``metrics`` are the ones allowed (:data:`METRICS`).
``expressions`` name a Django expression: :class:`TextNumber` reads numbers
stored as text, and any expression of your own works the same way
(``F("price") - F("cost")``, ``ExtractYear("launched_on")``).

The request (:func:`parse_query`) names ``group_by``, ``metric`` (default
``count``), ``value``, ``top`` (the largest N groups, the rest in one
"Other" group), and ``stack`` or ``series`` (a second dimension). The result
(:func:`run_aggregate`) is one query, or two with "Other".

Override / escape hatch: a viewset's ``aggregation`` declaration wins over
the model's, ``get_aggregation()`` computes one per request, and
``aggregate_queryset()`` changes the rows. An expression of your own goes in
``expressions``. Anything else is a hand-written ``@action``.
"""

from __future__ import annotations

import datetime
import decimal
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db import models
from django.db.models import (
    Avg,
    Case,
    Count,
    F,
    FloatField,
    Max,
    Min,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.functions import (
    Cast,
    Replace,
    Trim,
    TruncMonth,
    TruncQuarter,
    TruncYear,
    Upper,
)
from django.db.models.lookups import Regex

from karni.errorcodes import KarniError
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

__all__ = [
    "BUCKETS",
    "DEFAULT_MAX_GROUPS",
    "KEYS",
    "METRICS",
    "PARAMETERS",
    "AggregateQuery",
    "Aggregation",
    "AggregationError",
    "Dimension",
    "TextNumber",
    "aggregation_of",
    "max_groups",
    "parse_query",
    "run_aggregate",
]

#: Experimental. The metrics a request may name, in the order the docs list them.
METRICS: Final[tuple[str, ...]] = ("count", "sum", "avg", "min", "max", "distinct_count")
#: Experimental. The date buckets a date or datetime field takes after a colon.
BUCKETS: Final[tuple[str, ...]] = ("year", "quarter", "month")
#: Experimental. The keys a declaration takes.
KEYS: Final[frozenset[str]] = frozenset({"group_by", "values", "metrics", "expressions"})
#: Experimental. The query parameters the aggregate action reads: never list filters there.
PARAMETERS: Final[tuple[str, ...]] = ("group_by", "metric", "value", "top", "stack", "series")
#: Experimental. ``KARNI_AGGREGATE_MAX_GROUPS`` when it is unset.
DEFAULT_MAX_GROUPS: Final = 1000

#: The metrics that read a number (``count`` and ``distinct_count`` take any value).
_NUMERIC_METRICS: Final = frozenset({"sum", "avg", "min", "max"})
#: Missing cells of a split read 0 for these (no rows), ``None`` for the others.
_ADDITIVE: Final = frozenset({"count", "distinct_count", "sum"})
_NUMBER_FIELDS: Final = (models.IntegerField, models.FloatField, models.DecimalField)
_DATE_FIELDS: Final = (models.DateField,)  # DateTimeField is a DateField
_TRUNC: Final = {"year": TruncYear, "quarter": TruncQuarter, "month": TruncMonth}
_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
#: The label of the group of rows whose key is empty, and of the "Other" group.
EMPTY_LABEL: Final = "(none)"
OTHER_LABEL: Final = "Other"

# annotation names: prefixed so they never meet a model field
_X, _XL, _Z, _ZL = "karni_agg_x", "karni_agg_x_label", "karni_agg_z", "karni_agg_z_label"
_M, _N, _R = "karni_agg_value", "karni_agg_rows", "karni_agg_rank"


class AggregationError(KarniError):
    """Experimental. A request the declaration does not allow: a 400 with the code."""


# text numbers ------------------------------------------------------------------------

#: Experimental. The suffixes :class:`TextNumber` reads, upper case, with their multipliers.
TEXT_NUMBER_SUFFIXES: Final[Mapping[str, float]] = {
    "K": 1e3,
    "THOUSAND": 1e3,
    "M": 1e6,
    "MM": 1e6,
    "MN": 1e6,
    "MILLION": 1e6,
    "B": 1e9,
    "BN": 1e9,
    "BILLION": 1e9,
    "T": 1e12,
    "TN": 1e12,
    "TRILLION": 1e12,
}
#: Experimental. What :class:`TextNumber` removes before it reads the number.
TEXT_NUMBER_STRIP: Final[tuple[str, ...]] = ("$", "€", "£", "¥", "₹", ",", " ")
_NUMBER: Final = r"-?[0-9]+(\.[0-9]+)?"


class TextNumber(Case):
    """Experimental. A number stored as text, read in SQL: ``"$1.2B"`` is 1200000000.0.

    For money and counts a source wrote as text (``"$1,045,000"``, ``"450K"``,
    ``"9.5 million"``, ``"2.1bn"``). It trims the text, upper-cases it,
    removes ``strip`` (currency signs, thousands separators and spaces), then
    reads a plain number, or a number followed by one of ``suffixes`` times
    its multiplier. Anything else (``"Undisclosed"``, ``""``, a range) is
    ``NULL``, never 0, so a sum or an average leaves it out. It runs on
    PostgreSQL and SQLite (Django's ``regex`` lookup on both), as a float::

        expressions = {"revenue": TextNumber("revenue_text")}
        expressions = {"amount": TextNumber("amount_text", suffixes={"CR": 1e7, "L": 1e5})}

    Override / escape hatch: pass ``suffixes`` and ``strip``, subclass it, or
    declare any other Django expression in ``expressions`` instead.
    """

    def __init__(
        self,
        source: str | Any,
        *,
        suffixes: Mapping[str, float] | None = None,
        strip: Sequence[str] | None = None,
    ) -> None:
        text: Any = Upper(Trim(F(source) if isinstance(source, str) else source))
        for token in TEXT_NUMBER_STRIP if strip is None else strip:
            text = Replace(text, Value(token), Value(""))
        whens = []
        table = TEXT_NUMBER_SUFFIXES if suffixes is None else suffixes
        # Longest first, so "MM" is never read as "M" (the anchors make it exact anyway).
        for suffix, multiplier in sorted(table.items(), key=lambda item: -len(item[0])):
            word = str(suffix).upper()
            pattern = f"^{_NUMBER}{re.escape(word)}$"
            number = Cast(Replace(text, Value(word), Value("")), FloatField())
            whens.append(When(Regex(text, pattern), then=number * Value(float(multiplier))))
        whens.append(When(Regex(text, f"^{_NUMBER}$"), then=Cast(text, FloatField())))
        super().__init__(*whens, default=Value(None), output_field=FloatField())


# the declaration -----------------------------------------------------------------------


def _names(owner: str, key: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise KarniImproperlyConfigured(
            f"{owner} {key} must be a list of names, e.g. [{value!r}].", code="E380"
        )
    if not all(isinstance(item, str) and item for item in value):
        raise KarniImproperlyConfigured(
            f"{owner} {key} must list names (text), got {list(value)!r}.", code="E380"
        )
    return tuple(dict.fromkeys(value))


@dataclass(frozen=True)
class Aggregation:
    """Experimental. What a resource may be aggregated by (see the module docstring).

    ``group_by``: fields, relation paths or expression names a request may
    group by, a date field with or without a bucket (``launched_on:year``).
    ``values``: what a metric other than a plain count may read.
    ``metrics``: the metrics allowed (default: all of :data:`METRICS`).
    ``expressions``: name -> Django expression, usable in both lists.

    Declared as ``class Karni: aggregate = {...}`` on the model (a dict or an
    ``Aggregation``), or ``aggregation = Aggregation(...)`` on the viewset,
    which wins.
    """

    group_by: Sequence[str] = ()
    values: Sequence[str] = ()
    metrics: Sequence[str] = METRICS
    expressions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        owner = "Aggregation"
        object.__setattr__(self, "group_by", _names(owner, "group_by", self.group_by))
        object.__setattr__(self, "values", _names(owner, "values", self.values))
        metrics = _names(owner, "metrics", self.metrics)
        unknown = [metric for metric in metrics if metric not in METRICS]
        if unknown:
            raise KarniImproperlyConfigured(
                f"{owner} metrics names {', '.join(unknown)}: the metrics are "
                f"{', '.join(METRICS)}.",
                code="E380",
            )
        object.__setattr__(self, "metrics", metrics)
        if not isinstance(self.expressions, Mapping):
            raise KarniImproperlyConfigured(
                f"{owner} expressions must map a name to a Django expression, e.g. "
                "{'revenue': TextNumber('revenue_text')}.",
                code="E380",
            )
        for name, expression in self.expressions.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
                raise KarniImproperlyConfigured(
                    f"{owner} expression name {name!r} must be a lowercase identifier.",
                    code="E380",
                )
            if not hasattr(expression, "resolve_expression"):
                raise KarniImproperlyConfigured(
                    f"{owner} expressions[{name!r}] must be a Django expression (F(...), "
                    f"TextNumber(...), ExtractYear(...)), got {expression!r}.",
                    code="E380",
                )

    @classmethod
    def coerce(cls, value: Any, owner: str) -> Aggregation:
        """Experimental. ``value`` (a dict or an ``Aggregation``) as an ``Aggregation``.

        :raises karni.exceptions.KarniImproperlyConfigured: (``E380``) for any
            other value or an unknown key.
        """
        if isinstance(value, Aggregation):
            return value
        if not isinstance(value, Mapping):
            raise KarniImproperlyConfigured(
                f"{owner} must be a dict ({{'group_by': [...], 'values': [...], 'metrics': "
                f"[...]}}) or an Aggregation, got {value!r}.",
                code="E380",
            )
        unknown = sorted(set(value) - KEYS)
        if unknown:
            raise KarniImproperlyConfigured(
                f"{owner} has unknown key(s) {', '.join(map(repr, unknown))}. It takes "
                f"{', '.join(sorted(KEYS))}.",
                code="E380",
            )
        try:
            return cls(
                group_by=value.get("group_by", ()),
                values=value.get("values", ()),
                metrics=value.get("metrics", METRICS),
                expressions=dict(value.get("expressions") or {}),
            )
        except KarniImproperlyConfigured as exc:
            raise KarniImproperlyConfigured(
                exc.message.replace("Aggregation", owner, 1), code="E380"
            ) from None

    def problems(self, model: type[models.Model]) -> list[str]:
        """Experimental. What in this declaration does not fit ``model`` (empty when all fits)."""
        found: list[str] = []
        if not self.group_by:
            found.append("group_by is empty: name at least one field to group by")
        for name, expression in self.expressions.items():
            try:
                _expression_field(model, expression)
            except (FieldError, FieldDoesNotExist, AttributeError, TypeError) as exc:
                found.append(f"expressions[{name!r}] does not resolve on {model.__name__}: {exc}")
        for entry in self.group_by:
            path, _, bucket = entry.partition(":")
            try:
                target = _target_field(model, path, self.expressions)
            except AggregationError as exc:
                found.append(f"group_by {entry!r}: {exc.message}")
                continue
            if bucket and bucket not in BUCKETS:
                found.append(
                    f"group_by {entry!r}: {bucket!r} is not a bucket ({', '.join(BUCKETS)})"
                )
            elif bucket and not isinstance(target, _DATE_FIELDS):
                found.append(f"group_by {entry!r}: a bucket needs a date or datetime field")
        for entry in self.values:
            try:
                _target_field(model, entry, self.expressions)
            except AggregationError as exc:
                found.append(f"values {entry!r}: {exc.message}")
        for key, entries in (("group_by", self.group_by), ("values", self.values)):
            for entry in entries:
                path = entry.partition(":")[0]
                if path in self.expressions:
                    continue
                try:
                    hops = _hops(model, path)
                except AggregationError:
                    continue  # reported above
                for owner, hop in hops:
                    if hop.name == "password" or hop.name in _write_only(owner):
                        found.append(
                            f"{key} {entry!r}: {owner.__name__}.{hop.name} is write-only, and "
                            "the API never shows it"
                        )
        return found

    def unused_expressions(self) -> list[str]:
        """Experimental. Expression names neither ``group_by`` nor ``values`` lists."""
        used = {entry.partition(":")[0] for entry in self.group_by} | set(self.values)
        return [name for name in self.expressions if name not in used]

    def allows_group(self, name: str) -> bool:
        """Experimental. Whether a request may group by ``name`` (``launched_on:year``)."""
        path = name.partition(":")[0]
        return name in self.group_by or path in self.group_by

    def describe(self, model: type[models.Model]) -> dict[str, Any]:
        """Experimental. The declaration as OpenAPI shows it (``x-karni-aggregate``)."""
        return {
            "group_by": list(self.group_options(model)),
            "values": list(self.values),
            "metrics": list(self.metrics),
        }

    def group_options(self, model: type[models.Model]) -> tuple[str, ...]:
        """Experimental. Every ``group_by`` value a request may send, buckets spelled out."""
        options: list[str] = []
        for entry in self.group_by:
            options.append(entry)
            if ":" in entry:
                continue
            try:
                target = _target_field(model, entry, self.expressions)
            except AggregationError:
                continue
            if isinstance(target, _DATE_FIELDS):
                options += [f"{entry}:{bucket}" for bucket in BUCKETS]
        return tuple(dict.fromkeys(options))


def aggregation_of(model: type[models.Model] | None) -> Aggregation | None:
    """Experimental. The model's ``class Karni: aggregate``, or ``None`` when it declares none.

    :raises karni.exceptions.KarniImproperlyConfigured: (``E380``) for a
        declaration that is not a dict or an ``Aggregation``.
    """
    if model is None:
        return None
    declared = karni_option(model, "aggregate")
    if declared is None or declared is False:
        return None
    return Aggregation.coerce(declared, f"{model.__name__}.Karni.aggregate")


def max_groups() -> int:
    """Experimental. ``KARNI_AGGREGATE_MAX_GROUPS``: the most groups one request returns."""
    from django.conf import settings

    return int(getattr(settings, "KARNI_AGGREGATE_MAX_GROUPS", DEFAULT_MAX_GROUPS))


# paths and fields ----------------------------------------------------------------------


def _expression_field(model: type[models.Model], expression: Any) -> Any:
    """The output field of ``expression`` resolved on ``model`` (no query runs)."""
    query = model._base_manager.none().annotate(**{_X: expression}).query
    return query.annotations[_X].output_field


def _hops(model: type[models.Model], path: str) -> list[tuple[type[models.Model], Any]]:
    """``(model, field)`` for each part of ``path``. A part that is not there raises ``E382``."""
    hops: list[tuple[type[models.Model], Any]] = []
    current = model
    parts = path.split("__")
    for index, part in enumerate(parts):
        try:
            found = current._meta.get_field(part)
        except FieldDoesNotExist:
            raise AggregationError(
                f"{current.__name__} has no field {part!r}", code="E382"
            ) from None
        hops.append((current, found))
        if index < len(parts) - 1:
            if not found.is_relation or found.related_model is None:
                raise AggregationError(
                    f"{current.__name__}.{part} is not a relation, so {path!r} cannot go "
                    "through it",
                    code="E382",
                )
            current = found.related_model
    return hops


def _target_field(model: type[models.Model], name: str, expressions: Mapping[str, Any]) -> Any:
    """The field ``name`` ends at: an expression's output field, or the path's last field."""
    if name in expressions:
        return _expression_field(model, expressions[name])
    return _hops(model, name)[-1][1]


def _write_only(model: type[models.Model]) -> frozenset[str]:
    return frozenset(getattr(getattr(model, "APIMeta", None), "write_only", None) or ())


def _references(expression: Any) -> set[str]:
    """The field paths an expression reads through ``F()``."""
    found: set[str] = set()
    stack = [expression]
    while stack:
        node = stack.pop()
        if isinstance(node, F):
            found.add(str(node.name))
            continue
        getter = getattr(node, "get_source_expressions", None)
        if callable(getter):
            stack.extend(item for item in getter() if item is not None)
    return found


def _check_visible(model: type[models.Model], path: str, user: Any, code: str, what: str) -> None:
    """Refuse a path through a field the requester may not read (``field_roles``, write-only)."""
    from karni.accounts.visibility import hidden_fields

    for owner, hop in _hops(model, path):
        name = hop.name
        if name == "password" or name in _write_only(owner) or name in hidden_fields(owner, user):
            raise AggregationError(
                f"{what} {path!r} is not available: {owner.__name__}.{name} is hidden from "
                "this requester.",
                code=code,
            )


# the request ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dimension:
    """Experimental. One grouping of a request: its key expression, label expression and kind.

    ``kind`` is ``relation`` (the key is the related row's key, the label its
    natural key), ``date`` (a bucket, or a plain date), ``choice``, ``bool``
    or ``plain``.
    """

    name: str
    path: str
    bucket: str
    key: Any
    label: Any
    kind: str
    choices: Mapping[str, str] = field(default_factory=dict)

    def label_of(self, key: Any, label: Any) -> str:
        """The label a group with ``key`` (and the label column's ``label``) shows."""
        if key is None:
            return EMPTY_LABEL
        if self.kind == "relation":
            return str(label) if label not in (None, "") else str(key)
        if self.kind == "bool":
            return "Yes" if key else "No"
        if self.kind == "choice":
            return str(self.choices.get(str(key), key))
        if self.kind == "date":
            return _date_label(key, self.bucket)
        return str(key)

    def json_key(self, key: Any) -> Any:
        """``key`` as JSON: a bucket as ``2024``, ``2024-Q1`` or ``2024-01``, a UUID as text."""
        if key is None:
            return None
        if self.kind == "date" and isinstance(key, datetime.date):
            return _date_key(key, self.bucket)
        return _json(key)


def _json(value: Any) -> Any:
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _date_key(value: datetime.date, bucket: str) -> str:
    if bucket == "year":
        return f"{value.year:04d}"
    if bucket == "quarter":
        return f"{value.year:04d}-Q{(value.month - 1) // 3 + 1}"
    if bucket == "month":
        return f"{value.year:04d}-{value.month:02d}"
    return value.isoformat()


def _date_label(value: Any, bucket: str) -> str:
    if not isinstance(value, datetime.date):
        return str(value)
    if bucket == "year":
        return f"{value.year}"
    if bucket == "quarter":
        return f"Q{(value.month - 1) // 3 + 1} {value.year}"
    if bucket == "month":
        return f"{_MONTHS[value.month - 1]} {value.year}"
    return value.isoformat()


def _dimension(
    aggregation: Aggregation,
    model: type[models.Model],
    name: str,
    user: Any,
    parameter: str,
) -> Dimension:
    """Resolve one ``group_by`` / ``stack`` / ``series`` value, or raise ``E382`` / ``E385``."""
    from karni.accounts.visibility import hidden_fields
    from karni.meta import natural_key

    path, _, bucket = name.partition(":")
    if not aggregation.allows_group(name):
        allowed = ", ".join(aggregation.group_options(model)) or "nothing"
        raise AggregationError(
            f"{parameter}={name!r} is not declared for {model.__name__}. Allowed: {allowed}.",
            code="E382",
        )
    if path in aggregation.expressions:
        expression = aggregation.expressions[path]
        for read in sorted(_references(expression)):
            _check_visible(model, read, user, "E382", parameter)
        target = _expression_field(model, expression)
        key: Any = expression
    else:
        _check_visible(model, path, user, "E382", parameter)
        target = _hops(model, path)[-1][1]
        key = F(path)
    if bucket:
        if bucket not in BUCKETS:
            raise AggregationError(
                f"{parameter}={name!r}: {bucket!r} is not a bucket. Buckets: {', '.join(BUCKETS)}.",
                code="E385",
            )
        if not isinstance(target, _DATE_FIELDS):
            raise AggregationError(
                f"{parameter}={name!r}: a bucket needs a date or datetime field, and {path!r} "
                "is not one.",
                code="E385",
            )
        output = models.DateTimeField() if isinstance(target, models.DateTimeField) else None
        trunc = _TRUNC[bucket]
        key = trunc(key, output_field=output) if output is not None else trunc(key)
        return Dimension(name, path, bucket, key, None, "date")
    if isinstance(target, _DATE_FIELDS):
        return Dimension(name, path, "", key, None, "date")
    if path not in aggregation.expressions and getattr(target, "is_relation", False):
        related = target.related_model
        label = None
        shown = natural_key(related) if related is not None else None
        if shown is not None and shown not in hidden_fields(related, user):
            label = F(f"{path}__{shown}")
        return Dimension(name, path, "", key, label, "relation")
    if isinstance(target, models.BooleanField):
        return Dimension(name, path, "", key, None, "bool")
    choices = getattr(target, "flatchoices", None) or ()
    if choices:
        mapped = {str(value): str(label) for value, label in choices}
        return Dimension(name, path, "", key, None, "choice", mapped)
    return Dimension(name, path, "", key, None, "plain")


@dataclass(frozen=True)
class AggregateQuery:
    """Experimental. One aggregate request, checked against the declaration (``parse_query``)."""

    group_by: Dimension
    metric: str = "count"
    value: str | None = None
    value_expression: Any = None
    value_label: str = ""
    top: int | None = None
    split: Dimension | None = None
    stacked: bool = False

    def aggregate(self) -> Any:
        """A fresh aggregate expression for the metric (``Count``, ``Sum``, ...)."""
        target = self.value_expression if self.value_expression is not None else "pk"
        if self.metric == "count":
            return Count(target)
        if self.metric == "distinct_count":
            return Count(target, distinct=True)
        function = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[self.metric]
        return function(target)

    @property
    def series_label(self) -> str:
        """What the one series of an unsplit result is called: ``Count``, ``Sum of price``."""
        what = self.value_label
        text = {
            "count": f"Count of {what}" if what else "Count",
            "distinct_count": f"Distinct {what}",
            "sum": f"Sum of {what}",
            "avg": f"Average {what}",
            "min": f"Lowest {what}",
            "max": f"Highest {what}",
        }[self.metric]
        return text[:1].upper() + text[1:]


def _int(value: str, parameter: str, limit: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if not 1 <= number <= limit:
        raise AggregationError(
            f"{parameter}={value!r} must be a whole number from 1 to {limit}.", code="E386"
        )
    return number


def parse_query(
    aggregation: Aggregation,
    model: type[models.Model],
    params: Mapping[str, Any],
    *,
    user: Any = None,
) -> AggregateQuery:
    """Experimental. The request's parameters, checked against ``aggregation``.

    ``params`` is a mapping of the query parameters (a ``QueryDict`` works).
    Fields hidden from ``user`` (``Karni.field_roles``, ``APIMeta.write_only``)
    are refused like undeclared ones.

    :raises AggregationError: with the code of the first problem: ``E382`` a
        grouping that is not declared, ``E383`` a metric, ``E384`` a value,
        ``E385`` a bucket, ``E386`` any other parameter.
    """
    group = str(params.get("group_by") or "")
    if not group:
        allowed = ", ".join(aggregation.group_options(model)) or "nothing"
        raise AggregationError(
            f"group_by is required: the field to group {model.__name__} by. Allowed: {allowed}.",
            code="E382",
        )
    dimension = _dimension(aggregation, model, group, user, "group_by")
    metric = str(params.get("metric") or "count")
    if metric not in METRICS or metric not in aggregation.metrics:
        raise AggregationError(
            f"metric={metric!r} is not allowed for {model.__name__}. Allowed: "
            f"{', '.join(aggregation.metrics)}.",
            code="E383",
        )
    value = str(params.get("value") or "") or None
    expression: Any = None
    value_label = ""
    if value is None and metric != "count":
        raise AggregationError(
            f"metric={metric} needs value=<field>, one of "
            f"{', '.join(aggregation.values) or '(none declared)'}.",
            code="E384",
        )
    if value is not None:
        if value not in aggregation.values:
            raise AggregationError(
                f"value={value!r} is not declared for {model.__name__}. Allowed: "
                f"{', '.join(aggregation.values) or 'nothing'}.",
                code="E384",
            )
        if value in aggregation.expressions:
            expression = aggregation.expressions[value]
            for read in sorted(_references(expression)):
                _check_visible(model, read, user, "E384", "value")
            target = _expression_field(model, expression)
            value_label = value.replace("_", " ")
        else:
            _check_visible(model, value, user, "E384", "value")
            target = _hops(model, value)[-1][1]
            expression = F(value)
            value_label = str(getattr(target, "verbose_name", value))
        if metric in _NUMERIC_METRICS and not isinstance(target, _NUMBER_FIELDS):
            raise AggregationError(
                f"metric={metric} needs a number, and value={value!r} is not one (count or "
                "distinct_count read any value).",
                code="E384",
            )
    top_param = params.get("top")
    top = _int(str(top_param), "top", max_groups()) if top_param not in (None, "") else None
    stack, series = params.get("stack") or "", params.get("series") or ""
    if stack and series:
        raise AggregationError(
            "Send stack or series, not both: each names the second dimension.", code="E386"
        )
    split = None
    split_name = str(stack or series)
    if split_name:
        parameter = "stack" if stack else "series"
        if split_name.partition(":")[0] == group.partition(":")[0]:
            raise AggregationError(
                f"{parameter}={split_name!r} groups by the same field as group_by.", code="E386"
            )
        split = _dimension(aggregation, model, split_name, user, parameter)
    return AggregateQuery(
        group_by=dimension,
        metric=metric,
        value=value,
        value_expression=expression,
        value_label=value_label,
        top=top,
        split=split,
        stacked=bool(stack),
    )


# running ------------------------------------------------------------------------------


def _number(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def _base(queryset: QuerySet[Any]) -> QuerySet[Any]:
    """``queryset`` unordered, behind ``pk IN (...)`` when it is distinct or annotated.

    A distinct queryset (a search across a to-many relation) or one with
    annotations (a search rank, an overridden ``get_queryset``) would change
    the GROUP BY, so the rows are taken by key instead: same rows, one query.
    """
    plain = queryset.order_by()
    query = plain.query
    if query.distinct or query.combinator or query.annotations or query.extra:
        return queryset.model._base_manager.filter(pk__in=plain.values("pk"))
    return plain


def _annotations(dimension: Dimension, key: str, label: str) -> dict[str, Any]:
    found = {key: dimension.key}
    if dimension.label is not None:
        found[label] = dimension.label
    return found


def _columns(dimension: Dimension, key: str, label: str) -> list[str]:
    return [key, label] if dimension.label is not None else [key]


def _too_many(limit: int) -> AggregationError:
    return AggregationError(
        f"The request makes more than {limit} groups (KARNI_AGGREGATE_MAX_GROUPS). Pass "
        "top=<n> to keep the largest groups and put the rest in Other, or narrow it with "
        "filters.",
        code="E387",
    )


def _sorted(dimension: Dimension, entries: list[dict[str, Any]], by_key: bool) -> None:
    """Order categories: by key (a relation by its label), else by value, largest first."""
    if by_key:

        def key_of(entry: dict[str, Any]) -> tuple[bool, Any]:
            raw = entry["label"].lower() if dimension.kind == "relation" else entry["sort"]
            return (entry["sort"] is None, raw if raw is not None else "")

        entries.sort(key=key_of)
    else:
        entries.sort(key=lambda entry: (entry["total"] is None, -(entry["total"] or 0)))


def run_aggregate(
    queryset: QuerySet[Any], query: AggregateQuery, *, limit: int | None = None
) -> dict[str, Any]:
    """Experimental. Run ``query`` over ``queryset``: one query, or two with ``top`` ("Other").

    ``queryset`` is the rows the list shows (access and filters applied).
    The result::

        {"group_by": "region", "metric": "sum", "value": "price", "split": None,
         "stacked": False, "top": None,
         "categories": [{"key": "eu", "label": "Europe", "other": False}, ...],
         "series": [{"key": None, "label": "Sum of price", "values": [1250.0, ...]}]}

    ``series`` holds one entry per value of the second dimension (one entry
    without it), each with a value per category, in the categories' order.
    Dates are ordered by key, everything else by value, largest first.
    "Other" comes last.

    :raises AggregationError: (``E387``) when more groups than ``limit``
        (``KARNI_AGGREGATE_MAX_GROUPS``) come back.
    """
    limit = limit if limit is not None else max_groups()
    base = _base(queryset)
    x, split = query.group_by, query.split
    with_x = base.annotate(**_annotations(x, _X, _XL))
    x_columns = _columns(x, _X, _XL)
    z_columns = _columns(split, _Z, _ZL) if split is not None else []
    other: list[dict[str, Any]] = []
    if split is None:
        grouped = with_x.values(*x_columns).annotate(**{_M: query.aggregate()})
        if query.top is not None:
            ranked = grouped.filter(**{f"{_X}__isnull": False}).order_by(
                F(_M).desc(nulls_last=True), _X
            )
            rows = list(ranked[: query.top])
            other = _other(with_x, query, [row[_X] for row in rows], [])
        else:
            rows = list(grouped.order_by(_X)[: limit + 1])
    else:
        with_both = with_x.annotate(**_annotations(split, _Z, _ZL))
        grouped = with_both.values(*x_columns, *z_columns).annotate(**{_M: query.aggregate()})
        if query.top is not None:
            ranking = (
                with_x.filter(**{f"{_X}__isnull": False})
                .values(_X)
                .annotate(**{_R: query.aggregate()})
                .order_by(F(_R).desc(nulls_last=True), _X)
                .values(_X)[: query.top]
            )
            rows = list(grouped.filter(**{f"{_X}__in": ranking}).order_by(_X)[: limit + 1])
            other = _other(with_both, query, ranking, z_columns)
        else:
            rows = list(grouped.order_by(_X, _Z)[: limit + 1])
    if len(rows) > limit:
        raise _too_many(limit)
    return _result(query, rows, other)


def _other(
    annotated: QuerySet[Any], query: AggregateQuery, keys: Any, z_columns: list[str]
) -> list[dict[str, Any]]:
    """The "Other" group: the rows outside the top keys (and the rows with no key)."""
    rest = Q(**{f"{_X}__isnull": True})
    if not isinstance(keys, list) or keys:
        rest |= ~Q(**{f"{_X}__in": keys})
    else:
        rest = Q()
    remaining = annotated.filter(rest)
    if not z_columns:
        found = remaining.aggregate(**{_M: query.aggregate(), _N: Count("pk")})
        return [found] if found[_N] else []
    grouped = remaining.values(*z_columns).annotate(**{_M: query.aggregate(), _N: Count("pk")})
    return [row for row in grouped.order_by(_Z) if row[_N]]


def _result(
    query: AggregateQuery, rows: list[dict[str, Any]], other: list[dict[str, Any]]
) -> dict[str, Any]:
    x, split = query.group_by, query.split
    fill = 0 if query.metric in _ADDITIVE else None
    categories: dict[Any, dict[str, Any]] = {}
    series: dict[Any, dict[str, Any]] = {}
    cells: dict[tuple[Any, Any], Any] = {}
    for row in rows:
        raw = row[_X]
        key = x.json_key(raw)
        if key not in categories:
            categories[key] = {
                "key": key,
                "label": x.label_of(raw, row.get(_XL)),
                "other": False,
                "sort": key if x.kind != "plain" else raw,
                "total": None,
            }
        z_key = split.json_key(row[_Z]) if split is not None else None
        if z_key not in series:
            label = (
                split.label_of(row[_Z], row.get(_ZL)) if split is not None else query.series_label
            )
            series[z_key] = {"key": z_key, "label": label}
        value = _number(row[_M])
        cells[(key, z_key)] = value
        if value is not None:
            total = categories[key]["total"]
            categories[key]["total"] = value if total is None else total + value
    ordered = list(categories.values())
    _sorted(x, ordered, by_key=x.kind == "date")
    other_key = object()
    if other:
        ordered.append({"key": None, "label": OTHER_LABEL, "other": True, "sort": None})
        for row in other:
            z_key = split.json_key(row[_Z]) if split is not None else None
            if z_key not in series:
                label = (
                    split.label_of(row[_Z], row.get(_ZL))
                    if split is not None
                    else query.series_label
                )
                series[z_key] = {"key": z_key, "label": label}
            cells[(other_key, z_key)] = _number(row[_M])
    if split is None and not series:
        series[None] = {"key": None, "label": query.series_label}
    ordered_series = list(series.values())
    if split is not None:
        ordered_series.sort(key=lambda entry: (entry["key"] is None, str(entry["key"])))
    for entry in ordered_series:
        entry["values"] = [
            cells.get((other_key if category["other"] else category["key"], entry["key"]), fill)
            for category in ordered
        ]
    return {
        "group_by": x.name,
        "metric": query.metric,
        "value": query.value,
        "split": split.name if split is not None else None,
        "stacked": query.stacked,
        "top": query.top,
        "categories": [
            {"key": entry["key"], "label": entry["label"], "other": entry["other"]}
            for entry in ordered
        ],
        "series": ordered_series,
    }
