"""Experimental. The OpenAPI side of ``GET <resource>/aggregate/`` (:mod:`karni.aggregation`).

:class:`AggregateResultSerializer` describes the response, so a typed client
(``openapi-typescript``, ``karni types``) gets ``AggregateResult``, and
:func:`aggregate_parameters` documents the action's own query parameters
with the values the resource declares as enums. The list filters are
documented on the operation too (:class:`karni.api.schema.KarniAutoSchema`),
and ``x-karni-aggregate`` carries the declaration (:meth:`Aggregation.describe`).

Override / escape hatch: a viewset that answers differently documents its
own response with ``@extend_schema`` on its ``aggregate`` override.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers

from karni.aggregation import METRICS, Aggregation

__all__ = [
    "AggregateCategorySerializer",
    "AggregateResultSerializer",
    "AggregateSeriesSerializer",
    "aggregate_parameters",
]


class AggregateCategorySerializer(serializers.Serializer[Any]):
    """Experimental. One group of the first dimension (a bar, a point on the x axis)."""

    key = serializers.JSONField(
        allow_null=True,
        help_text="The group's key: a value, a related row's key, or a date bucket (2024-Q1). "
        "null for rows with no value, and for Other.",
    )
    label = serializers.CharField(help_text="What the group is called.")
    other = serializers.BooleanField(help_text="True for the Other group that top adds.")


class AggregateSeriesSerializer(serializers.Serializer[Any]):
    """Experimental. One series: a value per category, in the categories' order."""

    key = serializers.JSONField(
        allow_null=True, help_text="The second dimension's key, null without one."
    )
    label = serializers.CharField(help_text="What the series is called.")
    values = serializers.ListField(
        child=serializers.FloatField(allow_null=True),
        help_text="A value per category. null where a metric has no value.",
    )


class AggregateResultSerializer(serializers.Serializer[Any]):
    """Experimental. The response of ``GET <resource>/aggregate/``."""

    group_by = serializers.CharField()
    metric = serializers.ChoiceField(choices=list(METRICS))
    value = serializers.CharField(allow_null=True)
    split = serializers.CharField(
        allow_null=True, help_text="The second dimension (stack or series), or null."
    )
    stacked = serializers.BooleanField(help_text="True when the second dimension came as stack.")
    top = serializers.IntegerField(allow_null=True)
    categories = AggregateCategorySerializer(many=True)
    series = AggregateSeriesSerializer(many=True)


def aggregate_parameters(aggregation: Aggregation, model: Any) -> list[OpenApiParameter]:
    """Experimental. The aggregate action's query parameters, with the declared values as enums."""
    groups = list(aggregation.group_options(model))

    def query(name: str, description: str, **extra: Any) -> OpenApiParameter:
        return OpenApiParameter(
            name=name, location=OpenApiParameter.QUERY, description=description, **extra
        )

    parameters = [
        query(
            "group_by",
            "What to group by: a declared field, relation path or expression. A date takes "
            ":year, :quarter or :month.",
            type=str,
            required=True,
            enum=groups,
        ),
        query(
            "metric",
            "What to compute per group (default count).",
            type=str,
            enum=list(aggregation.metrics),
        ),
        query(
            "top",
            "Keep the N largest groups and put the rest in one Other group.",
            type=OpenApiTypes.INT,
        ),
        query("stack", "A second dimension, stacked.", type=str, enum=groups),
        query("series", "A second dimension, as separate series.", type=str, enum=groups),
    ]
    value: dict[str, Any] = {"type": str}
    if aggregation.values:
        value["enum"] = list(aggregation.values)
    parameters.insert(
        2,
        query("value", "The declared field the metric reads (not needed for count).", **value),
    )
    return parameters
