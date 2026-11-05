"""karni-charts' error codes (prefix ``CHART``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain
CHART001`` and ``docs/errors.md`` include them. Codes are permanent: never
renumber or reuse one, append new codes at the end.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_charts"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="CHART001",
        title="The chart's source is not a resource with an aggregation",
        kind="exception",
        source=f"{_SOURCE}.services.source_viewset",
        why="A chart reads its data through the source resource's aggregate action, so the "
        "source must be a routed resource whose model declares class Karni: aggregate (or whose "
        "viewset declares aggregation).",
        fix="Pick one of the sources the admin offers, or declare an aggregation on the model "
        "the chart should read: class Karni: aggregate = {'group_by': [...], 'values': [...]}.",
    ),
    ErrorCode(
        code="CHART002",
        title="A filter the chart does not allow",
        kind="api",
        source=f"{_SOURCE}.services.chart_filters",
        why="A viewer may narrow a saved chart only with the filters its allowed_filters lists. "
        "The default_filters always apply.",
        fix="Send only the filters the chart allows, or add the filter's name to the chart's "
        "allowed_filters in the admin.",
    ),
    ErrorCode(
        code="CHART003",
        title="The chart's filters are not valid",
        kind="exception",
        source=f"{_SOURCE}.models.Chart.clean",
        why="default_filters maps a list filter to a value or a list of values, and "
        "allowed_filters lists the names of list filters. The aggregate's own parameters "
        "(group_by, metric, value, top, stack, series) are the chart's axes, never filters.",
        fix='Write default_filters as {"channel": "online"} and allowed_filters as '
        '["channel", "launched_on__gte"].',
    ),
    ErrorCode(
        code="CHART004",
        title="The chart's axes do not fit the source's aggregation",
        kind="exception",
        source=f"{_SOURCE}.models.Chart.clean",
        why="The x axis, the metric and value of the y axis and the z axis must be ones the "
        "source's aggregation declares (karni.aggregation). The message quotes the source's own "
        "refusal, with its E38x code.",
        fix="Choose a group, metric and value the source declares, or add them to the source "
        "model's class Karni: aggregate.",
    ),
)
