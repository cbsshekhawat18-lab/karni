"""System checks for lifecycle and limited-resource declarations (via :mod:`karni.checks`).

* ``karni.E988`` — a model with a ``StateField``, a ``CapacityField`` or a
  ``NoOverlap`` constraint that does not inherit ``karni.models.GuardedModel``
  (``BaseModel`` does): its saves would skip the transition checks, the
  conditional update and the named conflicts.
* ``karni.E986`` — ``CapacityField(total=...)`` names a field the model does
  not have, or one that is not an integer.
* ``karni.E987`` — a ``NoOverlap`` (``class Karni: no_overlap``) whose range
  is not a range field or a pair of comparable fields, or whose ``ignore``
  names an unknown field or an undeclared state.
* ``karni.W980`` — a ``NoOverlap`` on a database other than PostgreSQL:
  there is no ``EXCLUDE`` there, so overlaps are **not** enforced.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.db import connections, models, router

from karni.exceptions import check_error, check_warning

__all__ = ["check_guarded_models"]

_PAIR_KINDS = (models.DateTimeField, models.DateField, models.IntegerField, models.DecimalField)


def _field(model: type[models.Model], name: str) -> Any:
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _overlap_problems(model: type[models.Model], constraint: Any) -> list[str]:
    from karni.fields.state import StateField

    problems: list[str] = []
    span = constraint.span
    if isinstance(span, str):
        found = _field(model, span)
        if found is not None and not hasattr(found, "range_type"):
            problems.append(
                f"{span!r} is a {type(found).__name__}, not a range field: use "
                f"karni.fields.DateTimeRangeField, or a pair of fields: ({span!r}_start, "
                f"{span!r}_end)."
            )
    else:
        kinds = []
        for name in span:
            found = _field(model, name)
            if found is not None and not isinstance(found, _PAIR_KINDS):
                problems.append(
                    f"{name!r} is a {type(found).__name__}, but a (start, end) pair must be date, "
                    "date-time or number fields."
                )
            kinds.append(type(found))
        if len(set(kinds)) > 1 and not problems:
            problems.append(f"{span!r} mixes field types, but start and end must be the same type.")
    for name, values in constraint.ignore.items():
        found = _field(model, name)
        if found is None:
            problems.append(f"ignore names {name!r}, which {model.__name__} does not have.")
        elif isinstance(found, StateField):
            unknown = [value for value in values if value not in found.machine.states]
            if unknown:
                problems.append(
                    f"ignore[{name!r}] lists {', '.join(map(repr, unknown))}, which "
                    f"{'is' if len(unknown) == 1 else 'are'} not a state of {model.__name__}."
                    f"{name} ({', '.join(map(repr, found.machine.states))})."
                )
    return problems


def _vendor(model: type[models.Model]) -> str:
    alias = router.db_for_write(model) or "default"
    return str(connections[alias].vendor) if alias in connections.settings else "unknown"


@checks.register(checks.Tags.models)
def check_guarded_models(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E988 / E986 / E987 / W980 (see the module docstring)."""
    from karni.guards import guards_for
    from karni.models import GuardedModel

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    found: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            guards = guards_for(model)
            if not guards.active:
                continue
            if not issubclass(model, GuardedModel):
                found.append(
                    check_error(
                        "E988",
                        f"{model.__name__} declares a StateField, CapacityField or NoOverlap but "
                        "does not inherit karni.models.GuardedModel, so its saves skip the "
                        "transition checks, the conditional UPDATE and the named conflicts.",
                        hint="Inherit karni.models.BaseModel (which includes GuardedModel), or "
                        "add karni.models.GuardedModel to the model's bases.",
                        obj=model,
                    )
                )
            for capacity in guards.capacities:
                if capacity.total is None:
                    continue
                total = _field(model, capacity.total)
                if total is None or not isinstance(total, models.IntegerField):
                    what = "does not exist" if total is None else f"is a {type(total).__name__}"
                    found.append(
                        check_error(
                            "E986",
                            f"{model.__name__}.{capacity.name}: CapacityField(total="
                            f"{capacity.total!r}) names a field that {what}.",
                            hint="Point total= at the integer field holding the full quantity "
                            "on the same model, e.g. total='quantity'.",
                            obj=model,
                        )
                    )
            for constraint in guards.overlaps:
                for problem in _overlap_problems(model, constraint):
                    found.append(
                        check_error(
                            "E987",
                            f"{model.__name__}: no_overlap {constraint.name}: {problem}",
                            hint="Fix the NoOverlap declaration the message names.",
                            obj=model,
                        )
                    )
                vendor = _vendor(model)
                if vendor != "postgresql":
                    found.append(
                        check_warning(
                            "W980",
                            f"{model.__name__}: no_overlap ({constraint.name}) is NOT enforced: "
                            f"the {vendor} database has no EXCLUDE constraint, so overlapping "
                            "rows are accepted.",
                            hint="Run on PostgreSQL (where the database refuses overlaps), or "
                            "add 'karni.W980' to SILENCED_SYSTEM_CHECKS for a development "
                            "database where that is acceptable.",
                            obj=model,
                        )
                    )
    return found
