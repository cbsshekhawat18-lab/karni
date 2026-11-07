"""``Karni.dashboard``: the models a staff app's home page counts and lists.

A model opts in next to its other Karni options::

    class Order(BaseModel):
        status = StateField(states=[...], transitions={...})

        class Karni:
            dashboard = True                   # every default below

            dashboard = {                      # or say what to show
                "label": "Orders",             # default: the model's verbose_name_plural
                "order": 1,                    # position among the sections (default 0)
                "total": True,                 # a count of every row the user may read
                "new_days": 7,                 # a count of rows created in the last 7 days
                "by": "status",                # a count per value of this field
                "values": ["pending", "paid"], # only these values of `by`
                "counts": {"Due today": {"due_on": "today"}},  # named counts, by filter
                "recent": 5,                   # the newest rows, in a table
                "columns": ["number", "customer", "status"],
                "date_field": "created_at",    # what "new" and "newest" mean
            }

The declaration is published in the OpenAPI schema as ``x-karni-dashboard``
on the model's list operation (:func:`dashboard_spec`), and @karni/ui's
``<Dashboard>`` renders it: a ``Stat`` per count and a table of the newest
rows. Every number comes from the resource's own list endpoint with
``page_size=1`` and the count's filters, so the row scope, the access rules
and field visibility of the API apply unchanged. Nothing here runs a query.

Defaults: ``by`` is the model's first :class:`~karni.fields.StateField`, and
``values`` its states that are not terminal (the ones that still need
someone), or every choice of a plain choices field. ``date_field`` is
``created_at`` when the model has it. A filter value ``"today"``,
``"today-7"`` or ``"today+1"`` is a date relative to the day the page is
viewed (resolved in the browser).

A malformed declaration fails ``karni check`` with ``E133``.

Override / escape hatch: ``dashboard = False`` (or no declaration) leaves the
model out; ``<Dashboard resources={[...]}>`` or its ``sections`` / ``slots``
props replace the selection and every part of the page; a hand-written home
page can compose ``Stat`` and ``ResourceTable`` itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from django.core.exceptions import FieldDoesNotExist
from django.db import models

from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

__all__ = ["DASHBOARD_KEYS", "dashboard_spec"]

#: The keys ``Karni.dashboard`` accepts.
DASHBOARD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "label",
        "order",
        "total",
        "new_days",
        "by",
        "values",
        "counts",
        "recent",
        "columns",
        "date_field",
    }
)

#: How many newest rows the table shows by default (a dashboard is a glance).
DEFAULT_RECENT: Final = 5
#: The window of the "new" count by default.
DEFAULT_NEW_DAYS: Final = 7
#: The most rows the table may ask for: the API's smallest page-size cap.
MAX_RECENT: Final = 25
_DATE_TYPES: Final = ("DateTimeField", "DateField")
_FILTER_VALUE_TYPES: Final = (str, int, float, bool)


def _fail(model: type[models.Model], problem: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(
        f"{model.__name__}.Karni.dashboard {problem}",
        code="E133",
    )


def _field(model: type[models.Model], name: str, key: str) -> models.Field[Any, Any]:
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        names = ", ".join(f.name for f in model._meta.get_fields() if getattr(f, "concrete", False))
        raise _fail(
            model,
            f"{key} names {name!r}, which is not a field of {model.__name__}. Its fields: {names}.",
        ) from None
    return field  # type: ignore[return-value]


def _choices(field: models.Field[Any, Any]) -> list[str] | None:
    if field.get_internal_type() == "BooleanField":
        return ["true", "false"]
    choices = getattr(field, "choices", None)
    if not choices:
        return None
    return [str(value) for value, _ in field.flatchoices]


def _state_field(model: type[models.Model]) -> models.Field[Any, Any] | None:
    from karni.fields.state import StateField

    for field in model._meta.concrete_fields:
        if isinstance(field, StateField):
            return field
    return None


def _default_values(field: models.Field[Any, Any]) -> list[str]:
    machine = getattr(field, "machine", None)
    if machine is not None:
        open_states = [state for state in machine.states if machine.transitions[state]]
        return open_states or list(machine.states)
    return _choices(field) or []


def _int(model: type[models.Model], spec: Mapping[str, Any], key: str, default: int) -> int:
    value = spec.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _fail(model, f"{key} must be a whole number of 0 or more, got {value!r}.")
    return value


def _counts(model: type[models.Model], raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, Mapping):
        raise _fail(
            model,
            'counts must map a label to the filters it counts, e.g. {"Due today": '
            '{"due_on": "today"}}.',
        )
    counts: list[dict[str, Any]] = []
    for label, params in raw.items():
        if not isinstance(label, str) or not label.strip():
            raise _fail(model, f"counts has a label that is not text: {label!r}.")
        if not isinstance(params, Mapping) or not params:
            raise _fail(
                model,
                f"counts[{label!r}] must be a non-empty dict of API filters, e.g. "
                '{"status": "open"}.',
            )
        clean: dict[str, Any] = {}
        for name, value in params.items():
            _field(model, str(name).split("__", 1)[0], f"counts[{label!r}]")
            values = value if isinstance(value, list | tuple) else [value]
            if not all(isinstance(item, _FILTER_VALUE_TYPES) for item in values):
                raise _fail(
                    model,
                    f"counts[{label!r}][{name!r}] must be text, a number, a boolean or a list "
                    f"of them, got {value!r}.",
                )
            clean[str(name)] = list(values) if isinstance(value, list | tuple) else value
        counts.append({"label": label, "params": clean})
    return counts


def dashboard_spec(model: type[models.Model]) -> dict[str, Any] | None:
    """The normalized ``Karni.dashboard`` of ``model``, or ``None`` when it does not opt in.

    Every default is filled in, so the client never guesses: the label, the
    ``by`` field and its values, the date field, the columns. Raises
    :class:`~karni.exceptions.KarniImproperlyConfigured` (``E133``) for a
    declaration that cannot work.
    """
    declared = karni_option(model, "dashboard")
    if declared is None or declared is False:
        return None
    if declared is True:
        declared = {}
    if not isinstance(declared, Mapping):
        raise _fail(
            model,
            f"must be True or a dict, got {declared!r}. Example: dashboard = "
            '{"by": "status", "recent": 5}.',
        )
    unknown = sorted(set(declared) - DASHBOARD_KEYS)
    if unknown:
        raise _fail(
            model,
            f"has unknown keys: {', '.join(unknown)}. It accepts "
            f"{', '.join(sorted(DASHBOARD_KEYS))}.",
        )

    label = declared.get("label")
    if label is None:
        plural = str(model._meta.verbose_name_plural)
        label = plural[:1].upper() + plural[1:]
    elif not isinstance(label, str) or not label.strip():
        raise _fail(model, f"label must be text, got {label!r}.")

    order = declared.get("order", 0)
    if isinstance(order, bool) or not isinstance(order, int):
        raise _fail(model, f"order must be a whole number, got {order!r}.")

    total = declared.get("total", True)
    if not isinstance(total, bool):
        raise _fail(model, f"total must be True or False, got {total!r}.")

    date_field = declared.get("date_field")
    if date_field is None:
        names = {field.name for field in model._meta.concrete_fields}
        date_field = "created_at" if "created_at" in names else None
    elif not isinstance(date_field, str):
        raise _fail(model, f"date_field must be a field name, got {date_field!r}.")
    if date_field is not None:
        field = _field(model, date_field, "date_field")
        if field.get_internal_type() not in _DATE_TYPES:
            raise _fail(
                model,
                f"date_field {date_field!r} is a {field.get_internal_type()}: it must be a date "
                "or datetime field (what 'new' and 'newest' are measured by).",
            )

    new_days = _int(model, declared, "new_days", DEFAULT_NEW_DAYS if date_field else 0)
    if new_days and date_field is None:
        raise _fail(
            model,
            "new_days needs a date field to count by: the model has no created_at, so set "
            'date_field (e.g. "placed_at") or new_days = 0.',
        )
    recent = _int(model, declared, "recent", DEFAULT_RECENT)
    if recent > MAX_RECENT:
        raise _fail(model, f"recent is {recent}: show at most {MAX_RECENT} rows on a dashboard.")

    by = declared.get("by")
    if by is not None and not isinstance(by, str):
        raise _fail(model, f"by must be a field name, got {by!r}.")
    by_field = _field(model, by, "by") if by is not None else _state_field(model)
    values: list[str] = []
    if by_field is not None:
        choices = _choices(by_field)
        if choices is None:
            raise _fail(
                model,
                f"by names {by_field.name!r}, which has no choices: count by a StateField, a "
                "field with choices, or a BooleanField.",
            )
        raw_values = declared.get("values")
        if raw_values is None:
            values = _default_values(by_field)
        else:
            if isinstance(raw_values, str) or not isinstance(raw_values, list | tuple):
                raise _fail(model, f"values must be a list, got {raw_values!r}.")
            values = [
                str(value).lower() if isinstance(value, bool) else str(value)
                for value in raw_values
            ]
            wrong = [value for value in values if value not in choices]
            if wrong:
                raise _fail(
                    model,
                    f"values names {', '.join(map(repr, wrong))}, which {by_field.name!r} does "
                    f"not have. Its values: {', '.join(choices)}.",
                )
    elif declared.get("values") is not None:
        raise _fail(model, "values needs by: the field whose values it lists.")

    columns = declared.get("columns")
    if columns is not None:
        if isinstance(columns, str) or not isinstance(columns, list | tuple):
            raise _fail(model, f"columns must be a list of field names, got {columns!r}.")
        for name in columns:
            _field(model, str(name), "columns")
        columns = [str(name) for name in columns]

    return {
        "label": label,
        "order": order,
        "total": total,
        "new_days": new_days,
        "date_field": date_field,
        "by": by_field.name if by_field is not None else None,
        "values": values,
        "counts": _counts(model, declared.get("counts")),
        "recent": recent,
        "columns": columns,
    }
