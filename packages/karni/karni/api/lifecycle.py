"""The API side of lifecycle and limited-resource fields: serializer fields and their schema.

* A :class:`~karni.fields.StateField` becomes a :class:`StateChoiceField`:
  an enum in the OpenAPI document, plus ``x-karni-transitions`` (every
  state → the states it may move to; terminal states map to ``[]``) and
  ``x-karni-initial`` (the states a new row may start in), so a client such
  as ``@karni/ui`` can offer only legal actions. The server still enforces:
  an illegal transition is a 400 on the field (``E980``), a wrong initial
  state a 400 (``E982``).
* A range field (``DateRangeField`` / ``DateTimeRangeField``) becomes a
  :class:`RangeField`: ``{"lower": ..., "upper": ..., "bounds": "[)"}`` in
  and out (a ``[lower, upper]`` pair is accepted too), a lower bound after
  the upper one is a 400.

Override / escape hatch: declare the field on a hand-written serializer, or
set ``serializer_class`` on the viewset.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers

__all__ = ["RangeField", "StateChoiceField", "lifecycle_errors"]


class StateChoiceField(serializers.ChoiceField):
    """A ``ChoiceField`` that carries its StateField's lifecycle into the schema."""

    def __init__(self, *args: Any, machine: Any = None, **kwargs: Any) -> None:
        self.machine = machine
        super().__init__(*args, **kwargs)


class StateChoiceFieldExtension(OpenApiSerializerFieldExtension):
    """``enum`` plus ``x-karni-transitions`` and ``x-karni-initial``."""

    target_class = "karni.api.lifecycle.StateChoiceField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Any) -> Any:
        schema = auto_schema._map_serializer_field(self.target, direction, bypass_extensions=True)
        machine = getattr(self.target, "machine", None)
        if isinstance(schema, dict) and machine is not None:
            schema.update(machine.as_schema())
        return schema


_BOUNDS = ("[)", "(]", "()", "[]")


class RangeField(serializers.Field):  # type: ignore[type-arg]
    """``{"lower": <value>, "upper": <value>, "bounds": "[)"}`` for a PostgreSQL range column.

    ``model_field`` is the range model field; its ``base_field`` parses and
    renders each bound. ``null`` means an unbounded end.
    """

    default_error_messages = {
        "invalid": 'Expected {{"lower": ..., "upper": ..., "bounds": "[)"}} or [lower, upper].',
        "bounds": "bounds must be one of '[)', '(]', '()', '[]'.",
        "order": "The range starts after it ends ({lower} > {upper}).",
    }

    def __init__(self, *args: Any, model_field: Any = None, **kwargs: Any) -> None:
        self.model_field = model_field
        super().__init__(*args, **kwargs)

    def _bound(self) -> serializers.Field:  # type: ignore[type-arg]
        base = getattr(self.model_field, "base_field", None)
        if base is not None and base.get_internal_type() == "DateTimeField":
            return serializers.DateTimeField()
        if base is not None and base.get_internal_type() == "DateField":
            return serializers.DateField()
        if base is not None and base.get_internal_type() == "DecimalField":
            return serializers.DecimalField(max_digits=None, decimal_places=None)
        return serializers.IntegerField()

    def to_representation(self, value: Any) -> Any:
        if value is None:
            return None
        bound = self._bound()
        lower, upper = value.lower, value.upper
        return {
            "lower": None if lower is None else bound.to_representation(lower),
            "upper": None if upper is None else bound.to_representation(upper),
            "bounds": getattr(value, "bounds", None) or getattr(value, "_bounds", "[)"),
        }

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, list | tuple) and len(data) == 2:
            data = {"lower": data[0], "upper": data[1]}
        if not isinstance(data, dict) or not {"lower", "upper"} & set(data):
            self.fail("invalid")
        bounds = data.get("bounds") or getattr(self.model_field, "default_bounds", "[)")
        if bounds not in _BOUNDS:
            self.fail("bounds")
        bound = self._bound()
        lower = data.get("lower")
        upper = data.get("upper")
        lower = None if lower in (None, "") else bound.run_validation(lower)
        upper = None if upper in (None, "") else bound.run_validation(upper)
        if lower is not None and upper is not None and lower > upper:
            self.fail("order", lower=lower, upper=upper)
        return self.model_field.range_type(lower, upper, bounds)


class RangeFieldExtension(OpenApiSerializerFieldExtension):
    """An object with ``lower`` / ``upper`` (date or date-time) and ``bounds``."""

    target_class = "karni.api.lifecycle.RangeField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Any) -> Any:
        base = getattr(self.target.model_field, "base_field", None)
        kind = base.get_internal_type() if base is not None else ""
        bound: dict[str, Any] = {"type": "integer"}
        if kind == "DateTimeField":
            bound = {"type": "string", "format": "date-time"}
        elif kind == "DateField":
            bound = {"type": "string", "format": "date"}
        elif kind == "DecimalField":
            bound = {"type": "string", "format": "decimal"}
        return {
            "type": "object",
            "properties": {
                "lower": {**bound, "nullable": True},
                "upper": {**bound, "nullable": True},
                "bounds": {"type": "string", "enum": list(_BOUNDS), "default": "[)"},
            },
            "required": ["lower", "upper"],
            "x-karni-range": kind.removesuffix("Field").lower() or "range",
        }


def serializer_field(model_field: Any) -> tuple[type[Any], dict[str, Any]] | None:
    """The serializer field class and kwargs for a StateField or a range field, else ``None``."""
    from karni.fields.state import StateField

    if isinstance(model_field, StateField):
        return StateChoiceField, {"machine": model_field.machine}
    if hasattr(model_field, "range_type") and hasattr(model_field, "base_field"):
        return RangeField, {"model_field": model_field}
    return None


def lifecycle_errors(model: Any, validated: dict[str, Any], instance: Any = None) -> dict[str, Any]:
    """``{field: [message]}`` for every illegal state change in a create/update payload."""
    from karni.lifecycle import state_fields, transition_problem

    errors: dict[str, Any] = {}
    fields = state_fields(model)
    if not fields:
        return errors
    probe = instance if instance is not None else model()
    for field in fields:
        if field.name not in validated:
            if instance is None:
                problem = transition_problem(probe, field, getattr(probe, field.attname))
            else:
                continue
        else:
            problem = transition_problem(probe, field, validated[field.name])
        if problem is not None:
            from karni.exceptions import api_error

            errors.update(api_error(problem.code, problem.message, field=field.name).detail)
    return errors
